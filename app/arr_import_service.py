from app.arr_catalog import canonical_arr_record_path
from app.filesystem_paths import _canonical,_open_directory
from app.title_identity import validate_title_folder
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
from app.media_libraries import configured_media_libraries, is_tv_library, library_stage_paths

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




def _read_authority(*,settings=None):
    from app.json_arr_import_service import values
    return values(settings)


def library_config(values,name):
    from types import SimpleNamespace
    definition = next((item for item in configured_media_libraries(values) if item.name == name), None)
    if definition is None:
        raise ArrImportError('library_disabled')
    local, _ = library_stage_paths(values, name)[1:]
    return SimpleNamespace(name=name,media_type=definition.media_type,roots=tuple(local.items()))


def client_for(values, name, verify=lambda: None):
    config = library_config(values, name)
    prefix, service = ('SONARR', 'sonarr') if is_tv_library(name, config.media_type) else ('RADARR', 'radarr')
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
    """Check the complete catalog and stable IDs before treating a title as missing."""
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
    values = _read_authority(settings=settings)
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
    if _read_authority(settings=settings) != values:
        raise ArrImportError('binding_changed')
    return {'version': version, 'quality_profiles': [
        {key: p[key] for key in ('id', 'name')} for p in available_profiles],
        'folders': folders[:1000], 'folders_truncated': len(folders) > 1000,
        'folder_stages': {name: ' / '.join(locations[name]) for name in folders[:1000]},
        'monitoring': 'off', 'download_searches': False, 'read_only': True}


def lookup(*, library, term, settings=None):
    values = _read_authority(settings=settings)
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
    if _read_authority(settings=settings) != values:
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




def review(*,selection,settings=None):
    from app import json_arr_import_service
    return json_arr_import_service.review(selection=selection,settings=settings)


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


def apply(*,selection,expected_fingerprint,settings=None):
    from app import json_arr_import_service
    return json_arr_import_service.apply(selection=selection,expected_fingerprint=expected_fingerprint,settings=settings)


def recover(*,expected_fingerprint=None,settings=None):
    from app import json_arr_import_service
    return json_arr_import_service.recover(expected_fingerprint=expected_fingerprint,settings=settings)
