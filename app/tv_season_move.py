"""Journal one reversible season rename, using trusted protection and Sonarr adapters."""
from contextlib import ExitStack
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import stat

from app.arr_import_service import media_fingerprint
from app.atomic_rename import rename_directory_noreplace_at
from app.filesystem_paths import _canonical, _open_directory, scan_held_directory
from app.json_scan_control import KEY
from app.mount_identity import assert_rename_mount_binding, capture_rename_mount_binding
from app.title_identity import validate_title_folder

ARCHIVE = 'tv_leaving_soon_seasons'


def _identity(info):
    return [info.st_dev, info.st_ino]


def move_season(attempt, *, title, season, name, active_parent, holding_parent, restore,
                read_plan, monitoring):
    """Stage or restore one directory. A failure after intent requires review."""
    validate_title_folder(title)
    match = re.fullmatch(r'Season ([0-9]{1,4})', name, re.IGNORECASE)
    if (not match or type(season) is not int or season < 1
            or int(match[1]) != season or type(restore) is not bool
            or monitoring.season != season
            or type(monitoring.series_id) is not int or monitoring.series_id <= 0
            or Path(_canonical(monitoring.source_path)).name != title):
        raise ValueError('Regular season required')
    active, holding = (Path(_canonical(path)) for path in (active_parent, holding_parent))
    if (active.name != title or holding.name != title or active == holding
            or active in holding.parents or holding in active.parents):
        raise ValueError('Dedicated and distinct show directories required')
    session = attempt.session
    attempt._active()
    if any(root in session._path.parents for root in (active, holding)):
        raise ValueError('State must be outside the media directories')
    key = f'TV/{title}/{season}'
    archive = session.state.get(ARCHIVE, {})
    if not isinstance(archive, dict) or (key in archive) != restore:
        raise RuntimeError('Season tracking requires review')
    source_path, destination_path = (holding, active) if restore else (active, holding)

    with ExitStack() as stack:
        parents = []
        for path in (source_path, destination_path):
            fd = _open_directory(str(path))
            stack.callback(os.close, fd)
            parents.append((path, fd, _identity(os.fstat(fd))))
        source, destination = (parent[1] for parent in parents)
        witness = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK,
                          dir_fd=source)
        stack.callback(os.close, witness)
        binding = capture_rename_mount_binding(source, destination, witness)
        identity = _identity(os.fstat(witness))
        fingerprint, file_count = media_fingerprint(witness)

        def verify(moved=False):
            session.verify()
            for path, fd, expected in parents:
                reopened = _open_directory(str(path))
                try:
                    if _identity(os.fstat(reopened)) != expected:
                        raise RuntimeError('Season parent changed')
                finally:
                    os.close(reopened)
            assert_rename_mount_binding(binding, source, destination, witness)
            present, absent = (destination, source) if moved else (source, destination)
            item = os.stat(name, dir_fd=present, follow_symlinks=False)
            if not stat.S_ISDIR(item.st_mode) or _identity(item) != identity:
                raise RuntimeError('Season identity changed')
            with scan_held_directory(absent) as entries:
                for count, entry in enumerate(entries, 1):
                    alternate = re.fullmatch(r'Season ([0-9]{1,4})', entry.name, re.IGNORECASE)
                    if count > 1000 or (alternate and int(alternate[1]) == season):
                        raise RuntimeError('Season destination is occupied or could not be verified')
            if media_fingerprint(witness) != (fingerprint, file_count):
                raise RuntimeError('Season contents changed')

        verify()
        plan = read_plan()
        if plan.blocked or season not in (plan.restore if restore else plan.stage):
            raise RuntimeError('Season policy changed')
        previous = monitoring.read()
        if type(previous) is not bool:
            raise RuntimeError('Sonarr season monitoring unavailable')
        record = {'name': name, 'active_parent': str(active), 'holding_parent': str(holding),
                  'identity': identity, 'previous_monitoring': previous,
                  'sonarr_series_id': monitoring.series_id, 'sonarr_path': monitoring.source_path}
        if restore:
            record = archive[key]
            if (not isinstance(record, dict) or type(record.get('previous_monitoring')) is not bool
                    or record.get('identity') != identity or record.get('name') != name
                    or record.get('active_parent') != str(active)
                    or record.get('holding_parent') != str(holding)
                    or record.get('sonarr_series_id') != monitoring.series_id
                    or record.get('sonarr_path') != monitoring.source_path or previous):
                raise RuntimeError('Staged season identity or monitoring changed')
        wanted = record['previous_monitoring'] if restore else False
        verify()
        identifier = attempt.record_intent(kind='tv_season_move', library='TV', title=title,
            details={'key': key, 'record': record, 'restore': restore,
                     'fingerprint': fingerprint, 'file_count': file_count,
                     'staged_at': datetime.now(timezone.utc).isoformat()})
        journal = session.state[KEY]['journal']
        if not restore and previous:
            monitoring.set(False, expected=True)
            if monitoring.read() is not False:
                raise RuntimeError('Sonarr did not verify unmonitoring')
        plan = read_plan()
        if plan.blocked or season not in (plan.restore if restore else plan.stage):
            raise RuntimeError('Season policy changed before rename')
        verify()
        rename_directory_noreplace_at(source, name, destination, name)
        os.fsync(source)
        os.fsync(destination)
        verify(moved=True)
        if restore and wanted:
            monitoring.set(True, expected=False)
        if monitoring.read() is not wanted or monitoring.read() is not wanted:
            raise RuntimeError('Sonarr did not verify final monitoring')
        verify(moved=True)
        if restore:
            del archive[key]
        else:
            session.state.setdefault(ARCHIVE, {})[key] = {
                **record, 'staged_at': journal['details']['staged_at'],
            }
        attempt.finish_operation(identifier=identifier, verify_outcome=lambda _: True)
