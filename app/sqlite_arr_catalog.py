"""Bounded GET-only Arr catalogs and configured queue preparation.

No PUT/POST/DELETE, retries, request delivery or intent clearance. Every planned
request is resolved before the first media move. Credentials never enter state.
"""
from copy import deepcopy
from http.client import HTTPException
import json
from pathlib import PurePosixPath
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, ProxyHandler, build_opener

from app.sqlite_scheduled_paths import _canonical
from app.sqlite_scheduled_transport import _NoRedirect, _object
from app.sqlite_title_identity import validate_title_folder


def canonical_arr_record_path(value):
    """Accept one optional trailing slash on an otherwise canonical remote path.

    Do not normalize dot segments, duplicate separators, roots or aliases.
    Filesystem stage configuration continues to use the strict validator.
    """
    if isinstance(value, str) and value.endswith('/'):
        value = value[:-1]
    return _canonical(value)


class ArrCatalogError(RuntimeError):
    pass


class ArrCatalogGET:
    def __init__(self, *, service, base_url, token):
        if service not in ('radarr', 'sonarr'):
            raise ValueError('Known Arr service required')
        try:
            parsed = urlsplit(base_url)
            parsed.port
            valid = (parsed.scheme in ('http', 'https') and parsed.hostname
                and parsed.username is None and parsed.password is None
                and not parsed.query and not parsed.fragment
                and not any(part in ('.', '..') for part in parsed.path.split('/')))
        except (ValueError, TypeError):
            valid = False
        if (not valid or not isinstance(base_url, str) or chr(92) in base_url
                or any(ord(c) <= 32 or ord(c) == 127 for c in base_url)
                or not isinstance(token, str) or not token
                or any(ord(c) <= 32 or ord(c) == 127 for c in token)):
            raise ValueError('Valid Arr URL and API key required')
        self._url = base_url.rstrip('/') + '/api/v3/' + ('movie' if service == 'radarr' else 'series')
        self._token = token
        self._used = False
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    def __repr__(self):
        return '<ArrCatalogGET redacted>'

    def __call__(self):
        if self._used:
            raise ArrCatalogError('Arr catalog already requested; no retry')
        self._used = True
        try:
            request = Request(self._url, method='GET', headers={
                'X-Api-Key': self._token, 'Cache-Control': 'no-cache', 'Accept': 'application/json'})
            started = monotonic()
            with self._opener.open(request, timeout=10) as response:
                if response.status != 200:
                    raise ValueError('response')
                raw = bytearray()
                while True:
                    chunk = response.read1(min(65536, 8 * 1024 * 1024 + 1 - len(raw)))
                    if monotonic() - started >= 10:
                        raise ValueError('deadline')
                    raw.extend(chunk)
                    if len(raw) > 8 * 1024 * 1024:
                        raise ValueError('size')
                    if not chunk:
                        break
            def invalid(value):
                raise ValueError('nonfinite')
            data = json.loads(raw, object_pairs_hook=_object, parse_constant=invalid)
            if not isinstance(data, list) or len(data) > 100000:
                raise ValueError('catalog shape')
            return data
        except HTTPError as error:
            error.close()
            raise ArrCatalogError('Arr catalog unavailable or invalid') from None
        except (URLError, HTTPException, OSError, ValueError, TypeError, RuntimeError):
            raise ArrCatalogError('Arr catalog unavailable or invalid') from None


def configured_arr_queue_resolver(*, settings, config):
    """Detach active service configuration; returned callback performs reads once.

    Both URL/key blank disables that library's Arr queue integration. A partial
    configuration fails closed. Source paths must match the configured Arr view;
    destination APP_* aliases are kept separate from filesystem stage paths.
    Waiting-to-Keep preserves current monitoring; Holding-to-Keep enables it,
    matching existing JSON policy. Holding/Removal requests are unmonitored.
    """
    values = dict(settings)
    services = {}
    for library in config.libraries:
        service, prefix = ('radarr', 'RADARR') if library.jellyfin_type == 'Movie' else ('sonarr', 'SONARR')
        url, key = values.get(prefix + '_URL', ''), values.get(prefix + '_API_KEY', '')
        if not isinstance(url, str) or not isinstance(key, str):
            raise ValueError('Explicit Arr connection settings required')
        if not url.strip() and not key.strip():
            continue
        if not url.strip() or not key.strip():
            raise ValueError('Both Arr URL and API key are required')
        roots = {}
        for stage, path in library.roots:
            override = values.get(prefix + '_APP_' + stage.upper() + '_PATH', '') if stage != 'Waiting' else ''
            if not isinstance(override, str):
                raise ValueError('Explicit Arr application path required')
            roots[stage] = _canonical(override.strip() or path)
        services[library.name] = (service, ArrCatalogGET(service=service, base_url=url, token=key), roots)

    used = False
    def resolve(prepared):
        nonlocal used
        if used:
            raise ArrCatalogError('Arr request preparation cannot be replayed')
        used = True
        if prepared.configuration != config:
            raise ArrCatalogError('Arr preparation configuration mismatch')
        bindings = {binding.media_key: binding for binding in prepared.bindings}
        catalogs = {}
        requests = {}
        for move in prepared.plan.moves:
            if move.library not in services:
                continue
            service, fetch, roots = services[move.library]
            if move.library not in catalogs:
                by_folder, ids = {}, set()
                for item in fetch():
                    if (not isinstance(item, dict) or type(item.get('id')) is not int or item['id'] <= 0
                            or item['id'] in ids or type(item.get('monitored')) is not bool):
                        raise ArrCatalogError('Invalid or duplicate Arr stable identity')
                    path = canonical_arr_record_path(item.get('path'))
                    folder = validate_title_folder(PurePosixPath(path).name)
                    ids.add(item['id'])
                    if folder in by_folder:
                        raise ArrCatalogError('Ambiguous Arr title folder')
                    by_folder[folder] = (item['id'], path, item['monitored'])
                catalogs[move.library] = by_folder
            binding = bindings.get(move.media_key)
            if binding is None or binding.library != move.library:
                raise ArrCatalogError('Arr title binding mismatch')
            record = catalogs[move.library].get(binding.folder)
            if record is None or record[1] != roots[move.source_stage] + '/' + binding.folder:
                raise ArrCatalogError('Arr title source path missing or changed')
            monitored = (record[2] if move.source_stage == 'Waiting' else True) if move.destination_stage == 'Keep' else False
            requests[move.media_key] = {'service': service, 'title_id': record[0],
                'root': roots[move.destination_stage], 'monitored': monitored}
        return deepcopy(requests)
    return resolve
