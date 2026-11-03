"""Explicit existing-folder Arr registration, separate from lifecycle dispatch.

Imports are never automatic. Existing stage folders, unmonitored, no searches.
A durable intent precedes the one POST. Uncertainty blocks further execution
until explicit GET-only reconciliation; no create request is replayed.
"""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
from time import monotonic

from app.arr_import_transport import ArrImportHTTP, ArrImportError
from app.sqlite_arr_catalog import canonical_arr_record_path
from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_backend_gate import (require_sqlite_read_authority,
    require_sqlite_production_activation, live_release_enabled)
from app.sqlite_lock import audit_run_lock
from app.sqlite_operation_coordinator import INTENTS_KEY, SQLiteOperationCoordinator
from app.sqlite_scheduled_paths import _canonical, _open_directory
from app.sqlite_scheduled_production import _hold_control_database
from app.sqlite_scheduled_settings import scheduled_worker_from_settings
from app.sqlite_title_identity import validate_title_folder
from app.state_store import GuardedSQLiteStateStore

MEDIA_SUFFIXES = frozenset(('.mkv', '.mp4', '.m4v', '.avi', '.mov', '.ts', '.m2ts', '.mpg', '.mpeg', '.wmv', '.iso'))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
        allow_nan=False, separators=(',', ':')).encode('ascii')).hexdigest()


def positive(value):
    if type(value) is not int or not 0 < value < 2**31:
        raise ArrImportError('selection_invalid')
    return value


def text(value, limit=255):
    if (not isinstance(value, str) or not 1 <= len(value) <= limit
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ArrImportError('arr_response_invalid')
    return value


def library_config(values, name):
    if name not in ('Movies', 'TV'): raise ArrImportError('selection_invalid')
    libraries = [lib for lib in scheduled_worker_from_settings(values).libraries if lib.name == name]
    if len(libraries) != 1: raise ArrImportError('library_disabled')
    return libraries[0]


def client_for(values, name, verify=lambda: None):
    library_config(values, name)
    prefix, service = ('RADARR', 'radarr') if name == 'Movies' else ('SONARR', 'sonarr')
    return ArrImportHTTP(service=service, base_url=values.get(prefix + '_URL'),
        token=values.get(prefix + '_API_KEY'), verify=verify)


def check_version(client):
    status = client.get('system/status')
    version = status.get('version') if isinstance(status, dict) else None
    if not isinstance(version, str) or not re.fullmatch(r'\d+(?:\.\d+){1,4}', version):
        raise ArrImportError('arr_version_unavailable')
    if int(version.split('.')[0]) != (6 if client.service == 'radarr' else 4):
        raise ArrImportError('arr_version_unsupported')
    return version


def profiles(client):
    rows = client.get('qualityprofile')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
        raise ArrImportError('quality_profiles_unavailable')
    result, ids = [], set()
    for row in rows:
        if not isinstance(row, dict): raise ArrImportError('quality_profiles_unavailable')
        key = positive(row.get('id'))
        if key in ids: raise ArrImportError('quality_profiles_unavailable')
        ids.add(key); result.append({'id': key, 'name': text(row.get('name'), 128),
            '_configuration_sha256': digest(row)})
    return result


def checked_catalog(client):
    """Require complete stable identities before inferring that a title is absent."""
    provider = 'tmdbId' if client.service == 'radarr' else 'tvdbId'
    rows = client.get(client.resource)
    if not isinstance(rows, list) or len(rows) > 100000:
        raise ArrImportError('catalog_unavailable')
    ids, providers, folders, result = set(), set(), set(), []
    for row in rows:
        if not isinstance(row, dict): raise ArrImportError('catalog_unavailable')
        key, external = positive(row.get('id')), positive(row.get(provider))
        path = canonical_arr_record_path(row.get('path'))
        folder = PurePosixPath(path).name
        if key in ids or external in providers or folder in folders:
            raise ArrImportError('catalog_ambiguous')
        ids.add(key); providers.add(external); folders.add(folder)
        result.append({'id': key, provider: external, 'path': path})
    return result


def options(*, library, settings=None):
    values = require_sqlite_read_authority(settings=settings)
    config = library_config(values, library)
    client = client_for(values, library)
    version = check_version(client)
    available_profiles = profiles(client)
    locations, count = {}, 0
    for stage, root in config.roots:
        fd = _open_directory(root)
        try:
            with os.scandir(fd) as entries:
                for entry in entries:
                    if entry.name.startswith('.') or not entry.is_dir(follow_symlinks=False): continue
                    count += 1
                    if count > 100000: raise ArrImportError('inventory_limit')
                    locations.setdefault(entry.name, []).append(stage)
        finally: os.close(fd)
    folders = sorted(locations)
    if require_sqlite_read_authority(settings=settings) != values:
        raise ArrImportError('binding_changed')
    return {'version': version, 'quality_profiles': [
        {key: p[key] for key in ('id', 'name')} for p in available_profiles],
        'folders': folders[:1000], 'folders_truncated': len(folders) > 1000,
        'folder_stages': {name: ' / '.join(locations[name]) for name in folders[:1000]},
        'monitoring': 'off', 'download_searches': False, 'read_only': True}


def lookup(*, library, term, settings=None):
    values = require_sqlite_read_authority(settings=settings)
    client = client_for(values, library); check_version(client)
    records = client.get(client.resource + '/lookup', term=text(term, 200))
    if not isinstance(records, list) or len(records) > 1000:
        raise ArrImportError('lookup_unavailable')
    provider = 'tmdbId' if library == 'Movies' else 'tvdbId'
    rows, ids = [], set()
    for record in records:
        if not isinstance(record, dict): raise ArrImportError('lookup_unavailable')
        key = positive(record.get(provider))
        if key in ids: raise ArrImportError('lookup_ambiguous')
        ids.add(key)
        year = record.get('year')
        rows.append({'provider_id': key, 'title': text(record.get('title')),
            'year': year if type(year) is int and 1800 <= year <= 3000 else None})
    if require_sqlite_read_authority(settings=settings) != values:
        raise ArrImportError('binding_changed')
    return {'matches': rows[:20], 'truncated': len(rows) > 20, 'read_only': True}


def media_fingerprint(fd):
    rows, count, started = [], 0, monotonic()
    for base, dirs, files, directory in os.fwalk('.', dir_fd=fd, follow_symlinks=False):
        if len(PurePosixPath(base).parts) > 16: raise ArrImportError('inventory_limit')
        for name in sorted(dirs + files):
            count += 1
            if count > 20000 or monotonic() - started > 10:
                raise ArrImportError('inventory_limit')
            info = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                raise ArrImportError('unsafe_folder')
            if stat.S_ISREG(info.st_mode) and info.st_size > 0 and Path(name).suffix.lower() in MEDIA_SUFFIXES:
                rows.append([base, name, info.st_dev, info.st_ino, info.st_size,
                    info.st_mtime_ns, info.st_ctime_ns])
    if not rows: raise ArrImportError('no_existing_media')
    return digest(sorted(rows)), len(rows)


@contextmanager
def held_import(values, selection, *, verify_authority):
    if set(selection) != {'library', 'folder', 'provider_id', 'quality_profile_id'}:
        raise ArrImportError('selection_invalid')
    name, folder = selection['library'], validate_title_folder(selection['folder'])
    if folder.startswith('.'): raise ArrImportError('unsafe_folder')
    positive(selection['provider_id']); positive(selection['quality_profile_id'])
    config = library_config(values, name)
    roots = dict(config.roots)
    database = Path(values['SQLITE_STATE_FILE'])
    with ExitStack() as stack:
        parents = {}
        for stage, path in roots.items():
            parents[stage] = _open_directory(path); stack.callback(os.close, parents[stage])
        present = []
        for stage, fd in parents.items():
            try: item = os.stat(folder, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError: continue
            if not stat.S_ISDIR(item.st_mode): raise ArrImportError('unsafe_folder')
            present.append(stage)
        if len(present) != 1: raise ArrImportError('folder_changed')
        source_stage = present[0]
        title_fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=parents[source_stage]); stack.callback(os.close, title_fd)
        session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
        initial, revision = session.read_verified_snapshot()
        media, files = media_fingerprint(title_fd)
        title_identity = (os.fstat(title_fd).st_dev, os.fstat(title_fd).st_ino)
        def verify():
            verify_authority()
            present = []
            for stage, fd in parents.items():
                current_fd = _open_directory(roots[stage])
                try:
                    a, b = os.fstat(current_fd), os.fstat(fd)
                    if (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino): raise ArrImportError('folder_changed')
                finally: os.close(current_fd)
                try: item = os.stat(folder, dir_fd=fd, follow_symlinks=False)
                except FileNotFoundError: continue
                present.append(stage)
                if stage == source_stage and (not stat.S_ISDIR(item.st_mode)
                        or (item.st_dev, item.st_ino) != title_identity): raise ArrImportError('folder_changed')
            if present != [source_stage] or media_fingerprint(title_fd)[0] != media:
                raise ArrImportError('folder_changed')
            session.read_verified_snapshot()
        verify()
        prefix = 'RADARR' if name == 'Movies' else 'SONARR'
        override = (values.get(prefix + '_APP_' + source_stage.upper() + '_PATH', '').strip()
            if source_stage != 'Waiting' else '')
        remote_root = _canonical(override or roots[source_stage])
        yield session, verify, {'path': remote_root + '/' + folder,
            'root': remote_root, 'stage': source_stage, 'media_fingerprint': media, 'media_files': files,
            'title_identity': title_identity, 'state': initial, 'revision': revision}


def payload_review(client, selection, local):
    version = check_version(client)
    choices = profiles(client)
    selected = [p for p in choices if p['id'] == selection['quality_profile_id']]
    if len(selected) != 1: raise ArrImportError('quality_profile_changed')
    roots = client.get('rootfolder')
    if not isinstance(roots, list) or not any(isinstance(r, dict)
            and r.get('path') is not None and canonical_arr_record_path(r['path']) == local['root']
            and r.get('accessible') is True for r in roots):
        raise ArrImportError('arr_root_unavailable')
    provider = 'tmdbId' if client.service == 'radarr' else 'tvdbId'
    for row in checked_catalog(client):
        path = row['path']
        if row.get(provider) == selection['provider_id'] or PurePosixPath(path).name == selection['folder']:
            raise ArrImportError('already_managed_or_conflicting')
    prefix = 'tmdb:' if client.service == 'radarr' else 'tvdb:'
    records = client.get(client.resource + '/lookup', term=prefix + str(selection['provider_id']))
    matches = [r for r in records if isinstance(r, dict) and type(r.get(provider)) is int
        and r[provider] == selection['provider_id']] if isinstance(records, list) else []
    if len(matches) != 1: raise ArrImportError('provider_match_unavailable')
    record = matches[0]
    payload = {'title': text(record.get('title')), 'titleSlug': text(record.get('titleSlug')),
        provider: selection['provider_id'], 'qualityProfileId': selection['quality_profile_id'],
        'path': local['path'], 'rootFolderPath': local['root'], 'monitored': False, 'tags': []}
    year = record.get('year')
    if type(year) is not int or not 1800 <= year <= 3000: raise ArrImportError('provider_match_unavailable')
    payload['year'] = year
    if client.service == 'radarr':
        payload.update(minimumAvailability='released', addOptions={'monitor': 'none', 'searchForMovie': False})
    else:
        seasons, numbers = [], set()
        raw_seasons = record.get('seasons')
        if not isinstance(raw_seasons, list) or len(raw_seasons) > 1000:
            raise ArrImportError('provider_match_unavailable')
        for season in raw_seasons:
            number = season.get('seasonNumber') if isinstance(season, dict) else None
            if type(number) is not int or not 0 <= number <= 1000 or number in numbers:
                raise ArrImportError('provider_match_unavailable')
            numbers.add(number); seasons.append({'seasonNumber': number, 'monitored': False})
        series_type = record.get('seriesType', 'standard')
        if series_type not in ('standard', 'daily', 'anime'): raise ArrImportError('provider_match_unavailable')
        payload.update(seriesType=series_type, seasonFolder=True, seasons=seasons,
            monitorNewItems='none', addOptions={'monitor': 'none',
                'searchForMissingEpisodes': False, 'searchForCutoffUnmetEpisodes': False})
    summary = {'service': client.service, 'title': payload['title'], 'year': year,
        'path': local['path'], 'stage': local['stage'], 'quality_profile': selected[0]['name'], 'version': version,
        'monitoring': 'off', 'download_searches': False, 'media_files': local['media_files']}
    return payload, summary, selected[0]['_configuration_sha256']


@contextmanager
def locked_context(*, settings=None, execute=False):
    if execute and not live_release_enabled(): raise ArrImportError('live_import_unavailable')
    values = (require_sqlite_production_activation if execute else require_sqlite_read_authority)(settings=settings)
    database = Path(values['SQLITE_STATE_FILE'])
    with audit_run_lock(values['STATE_FILE']) as verify_json:
        with _hold_control_database(database.parent, database) as verify_control:
            def verify_authority():
                verify_json(); verify_control()
                if require_sqlite_read_authority(settings=settings) != values:
                    raise ArrImportError('binding_changed')
            verify_authority()
            yield values, verify_authority
            verify_authority()


def review(*, selection, settings=None):
    with locked_context(settings=settings) as (values, authority):
        with held_import(values, selection, verify_authority=authority) as (session, verify, local):
            if INTENTS_KEY in session.state: raise ArrImportError('pending_operation')
            client = client_for(values, selection['library'], verify)
            payload, summary, profile_hash = payload_review(client, selection, local)
            verify()
            fingerprint = digest({'payload': payload, 'local': local, 'settings': values,
                'quality_profile': profile_hash})
            return {**summary, 'review_fingerprint': fingerprint,
                'read_only': True, 'execution_authorized': False}


def verify_remote(client, details):
    provider = 'tmdbId' if client.service == 'radarr' else 'tvdbId'
    catalog = checked_catalog(client)
    matches = [r for r in catalog if isinstance(r, dict) and type(r.get(provider)) is int
        and r[provider] == details['provider_id']] if isinstance(catalog, list) else []
    if len(matches) != 1: raise ArrImportError('import_outcome_unverified')
    remote_id = positive(matches[0].get('id'))
    for _ in range(2):
        row = client.get(client.resource + '/' + str(remote_id))
        if (not isinstance(row, dict) or type(row.get('id')) is not int or row['id'] != remote_id
                or type(row.get(provider)) is not int or row[provider] != details['provider_id']
                or canonical_arr_record_path(row.get('path')) != details['path']
                or type(row.get('qualityProfileId')) is not int
                or row['qualityProfileId'] != details['quality_profile_id']
                or row.get('monitored') is not False):
            raise ArrImportError('import_outcome_unverified')
        if client.service == 'sonarr' and (row.get('monitorNewItems') != 'none'
                or not isinstance(row.get('seasons'), list)
                or any(not isinstance(s, dict) or s.get('monitored') is not False for s in row['seasons'])):
            raise ArrImportError('import_outcome_unverified')


def apply(*, selection, expected_fingerprint, settings=None):
    if not isinstance(expected_fingerprint, str) or not re.fullmatch('[0-9a-f]{64}', expected_fingerprint):
        raise ArrImportError('review_required')
    with locked_context(settings=settings, execute=True) as (values, authority):
        with held_import(values, selection, verify_authority=authority) as (session, verify, local):
            if INTENTS_KEY in session.state: raise ArrImportError('pending_operation')
            client = client_for(values, selection['library'], verify)
            payload, summary, profile_hash = payload_review(client, selection, local)
            if digest({'payload': payload, 'local': local, 'settings': values,
                    'quality_profile': profile_hash}) != expected_fingerprint:
                raise ArrImportError('review_changed')
            details = {**selection, 'path': local['path'], 'media_fingerprint': local['media_fingerprint'],
                'stage': local['stage'], 'title_identity': list(local['title_identity']), 'service': client.service}
            coordinator = SQLiteOperationCoordinator(session)
            coordinator.begin(secrets.token_hex(16), 'arr_import', details)
            intent = deepcopy(session.state[INTENTS_KEY])
            client.create(payload)  # The only create call; any failure retains the intent.
            verify_remote(client, details)
            verify()
            if session.state.get(INTENTS_KEY) != intent: raise ArrImportError('pending_operation_changed')
            session.state.pop(INTENTS_KEY)
            session.checkpoint(); verify()
            return {'status': 'existing_media_import_verified', 'state_revision': session.revision,
                'verification_scope': 'arr_record_registration', 'arr_file_scan_verified': False,
                'media_actions_performed': False, 'download_searches': False, 'monitoring': 'off',
                'automatic_retry': False, 'tracking_clocks_preserved': True, 'daily_claims_modified': False}


def recover(*, expected_fingerprint=None, settings=None):
    """Explicit GET-only review/clearance of one pending import, never another POST."""
    if not live_release_enabled(): raise ArrImportError('live_import_unavailable')
    with locked_context(settings=settings) as (values, authority):
        store = GuardedSQLiteStateStore(values['SQLITE_STATE_FILE'])
        state, revision = store.load_with_revision()
        intent = state.get(INTENTS_KEY)
        if (not isinstance(intent, dict) or set(intent) != {'id', 'kind', 'phase', 'details'}
                or not isinstance(intent.get('id'), str) or not re.fullmatch('[0-9a-f]{32}', intent['id'])
                or intent.get('kind') != 'arr_import'
                or intent.get('phase') != 'intent_recorded' or not isinstance(intent.get('details'), dict)):
            raise ArrImportError('no_pending_import')
        details = intent['details']
        if set(details) != {'library', 'folder', 'provider_id', 'quality_profile_id',
                'path', 'stage', 'media_fingerprint', 'title_identity', 'service'}:
            raise ArrImportError('pending_operation_changed')
        selection = {key: details[key] for key in ('library', 'folder', 'provider_id', 'quality_profile_id')}
        with held_import(values, selection, verify_authority=authority) as (session, verify, local):
            if (session.state != state or session.revision != revision
                    or details['path'] != local['path'] or details['stage'] != local['stage']
                    or details['media_fingerprint'] != local['media_fingerprint']
                    or details['title_identity'] != list(local['title_identity'])):
                raise ArrImportError('pending_operation_changed')
            fingerprint = digest({'state': state, 'revision': revision, 'local': local, 'settings': values})
            if expected_fingerprint is not None and fingerprint != expected_fingerprint:
                raise ArrImportError('review_changed')
            client = client_for(values, selection['library'], verify)
            if details['service'] != client.service: raise ArrImportError('pending_operation_changed')
            check_version(client); verify_remote(client, details); verify()
            if expected_fingerprint is None:
                return {'status': 'import_outcome_matches', 'review_fingerprint': fingerprint, 'read_only': True}
            session.state.pop(INTENTS_KEY); session.checkpoint(); verify()
            return {'status': 'import_intent_reconciled', 'state_revision': session.revision,
                'arr_create_requests_sent': 0, 'media_actions_performed': False, 'automatic_retry': False}
