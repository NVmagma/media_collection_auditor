"""Acknowledge completed season moves using filesystem observations and GETs."""
from contextlib import ExitStack
from datetime import datetime
from hashlib import sha256
import hmac
import json
import os
from pathlib import Path
import re

from app.arr_import_service import media_fingerprint
from app.filesystem_paths import _canonical, _open_directory
from app.json_scan_control import _control
from app.mount_identity import assert_rename_mount_binding, capture_rename_mount_binding
from app.sonarr_season_monitoring import SonarrSeasonMonitoring
from app.title_identity import validate_title_folder
from app.tv_season_move import ARCHIVE, SEASON_FOLDER, _identity, verify_season_location


def recover_season(store, *, settings, expected=None, monitoring_factory=SonarrSeasonMonitoring):
    """Review or explicitly acknowledge only the already-completed outcome."""
    if expected is not None and (not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected)):
        raise ValueError('Fresh season recovery review required')
    with store.session() as session, ExitStack() as stack:
        control = _control(session.state)
        journal = control['journal']
        if journal is None or journal['kind'] != 'tv_season_move' or journal['library'] != 'TV':
            raise RuntimeError('Pending TV season move required')
        title = validate_title_folder(journal['title'])
        details = journal['details']
        record = details['record']
        name, restore = record['name'], details['restore']
        match = SEASON_FOLDER.fullmatch(name)
        if not match or int(match[1]) < 1 or type(restore) is not bool:
            raise RuntimeError('Invalid season intent')
        season = int(match[1])
        key = f'TV/{title}/{season}'
        stamp = datetime.fromisoformat(details['staged_at'])
        archive = session.state.get(ARCHIVE, {})
        if (details['key'] != key or stamp.tzinfo is None or not isinstance(archive, dict)
                or type(record['previous_monitoring']) is not bool
                or (archive.get(key) != record if restore else key in archive)):
            raise RuntimeError('Season tracking changed')
        active, holding = (Path(_canonical(record[field])) for field in ('active_parent', 'holding_parent'))
        if (active.name != title or holding.name != title or active == holding
                or active in holding.parents or holding in active.parents
                or any(path in store.path.parents for path in (active, holding))):
            raise RuntimeError('Invalid season parent paths')
        paths = (holding, active) if restore else (active, holding)
        parents = []
        for path in paths:
            fd = _open_directory(str(path))
            stack.callback(os.close, fd)
            parents.append(fd)
        identities = [_identity(os.fstat(fd)) for fd in parents]
        if identities != details['parent_identities']:
            raise RuntimeError('Journaled season parent changed')
        source, destination = parents
        witness = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK,
                          dir_fd=destination)
        stack.callback(os.close, witness)
        binding = capture_rename_mount_binding(source, destination, witness)

        def verify():
            session.verify()
            for path, identity in zip(paths, identities, strict=True):
                fd = _open_directory(str(path))
                try:
                    if _identity(os.fstat(fd)) != identity:
                        raise RuntimeError('Season parent changed during review')
                finally:
                    os.close(fd)
            assert_rename_mount_binding(binding, source, destination, witness)
            verify_season_location(destination, source, name, season, record['identity'])
            if media_fingerprint(witness) != (details['fingerprint'], details['file_count']):
                raise RuntimeError('Journaled season contents changed')

        verify()
        monitor = monitoring_factory(base_url=settings.get('SONARR_URL', ''),
            token=settings.get('SONARR_API_KEY', ''), source_path=record['sonarr_path'],
            title_folder=title, series_id=record['sonarr_series_id'], season=season)
        wanted = record['previous_monitoring'] if restore else False
        if monitor.endpoint_identity != record['sonarr_endpoint'] or monitor.read() is not wanted or monitor.read() is not wanted:
            raise RuntimeError('Sonarr monitoring outcome could not be verified')
        verify()
        fingerprint = sha256(json.dumps([session._identity, journal, wanted],
                                        sort_keys=True).encode()).hexdigest()
        if expected is None:
            return {'status': 'season_move_reviewed', 'review_fingerprint': fingerprint,
                    'season': season, 'restored': restore, 'required_action': 'acknowledge_season_move'}
        if not hmac.compare_digest(expected, fingerprint):
            raise RuntimeError('Season recovery review changed')
        os.fsync(source)
        os.fsync(destination)
        verify()
        if restore:
            del archive[key]
        else:
            session.state.setdefault(ARCHIVE, {})[key] = {**record, 'staged_at': details['staged_at']}
        control['journal'] = None
        session.checkpoint()
        return {'status': 'season_move_reconciled', 'season': season, 'restored': restore}
