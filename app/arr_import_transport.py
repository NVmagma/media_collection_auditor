"""Import through the Arr v3 API without redirects, proxies, searches, or retries."""
import json
from time import monotonic
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request

from app.arr_catalog import ArrCatalogGET
from app.filesystem_paths import _canonical
from pathlib import PurePosixPath
from app.jellyfin_transport import _object


class ArrImportError(RuntimeError):
    """Use a fixed error code so responses and private URLs do not end up in errors."""


class ArrImportHTTP:
    def __init__(self, *, service, base_url, token, verify=lambda: None):
        client = ArrCatalogGET(service=service, base_url=base_url, token=token)
        self.resource = 'movie' if service == 'radarr' else 'series'
        self.service = service
        self._base = client._url.rsplit('/', 1)[0]
        self._opener, self._token = client._opener, client._token
        self._verify = verify
        self._deadline = monotonic() + 90
        self._posted = False

    def __repr__(self): return '<ArrImportHTTP redacted>'

    def _request(self, method, route, payload=None, query=None):
        self._verify()
        remaining = self._deadline - monotonic()
        if remaining <= 0: raise ArrImportError('arr_request_unavailable')
        url = self._base + '/' + route
        if query: url += '?' + urlencode(query)
        raw = None if payload is None else json.dumps(payload, allow_nan=False).encode()
        if raw is not None and len(raw) > 1024 * 1024:
            raise ArrImportError('import_payload_invalid')
        try:
            req = Request(url, method=method, data=raw, headers={
                'X-Api-Key': self._token, 'Accept': 'application/json',
                'Content-Type': 'application/json', 'Cache-Control': 'no-cache'})
            with self._opener.open(req, timeout=min(10, remaining)) as response:
                # v3 schemas document 200; current create controllers also return 201.
                # Check the result with fresh reads, even when the request was accepted.
                if response.status not in ((200, 201) if method == 'POST' else (200,)):
                    raise ValueError('status')
                body = bytearray()
                while True:
                    chunk = response.read1(min(65536, 8 * 1024 * 1024 + 1 - len(body)))
                    body.extend(chunk)
                    if len(body) > 8 * 1024 * 1024 or monotonic() >= self._deadline:
                        raise ValueError('limit')
                    if not chunk: break
            def invalid(_): raise ValueError('nonfinite')
            value = json.loads(body, object_pairs_hook=_object, parse_constant=invalid)
            if not isinstance(value, (dict, list)): raise ValueError('shape')
        except HTTPError as error:
            error.close()
            raise ArrImportError('arr_request_unavailable') from None
        except Exception:
            raise ArrImportError('arr_request_unavailable') from None
        self._verify()
        return value

    def get(self, route, *, term=None):
        allowed = {'system/status', 'qualityprofile', 'rootfolder', self.resource,
                   self.resource + '/lookup'}
        if route not in allowed:
            parts = route.split('/')
            if (len(parts) != 2 or parts[0] != self.resource or not parts[1].isascii()
                    or not parts[1].isdecimal() or int(parts[1]) <= 0):
                raise ArrImportError('arr_route_invalid')
        if term is not None and (route != self.resource + '/lookup'
                or not isinstance(term, str) or not 1 <= len(term) <= 200
                or any(ord(c) < 32 or ord(c) == 127 for c in term)):
            raise ArrImportError('lookup_invalid')
        return self._request('GET', route, query={'term': term} if term is not None else None)

    def create(self, payload):
        if self._posted: raise ArrImportError('import_attempt_already_used')
        self._posted = True  # A lost response still uses this attempt. Do not send it again.
        provider = 'tmdbId' if self.service == 'radarr' else 'tvdbId'
        fields = {'title', 'titleSlug', provider, 'qualityProfileId', 'path',
            'rootFolderPath', 'monitored', 'tags', 'year', 'addOptions'}
        extra = {'minimumAvailability'} if self.service == 'radarr' else {
            'seriesType', 'seasonFolder', 'seasons', 'monitorNewItems'}
        options = ({'monitor': 'none', 'searchForMovie': False} if self.service == 'radarr'
            else {'monitor': 'none', 'searchForMissingEpisodes': False, 'searchForCutoffUnmetEpisodes': False})
        if (not isinstance(payload, dict) or set(payload) != fields | extra
                or payload.get('monitored') is not False or payload.get('tags') != []
                or payload.get('addOptions') != options
                or any(type(payload.get(key)) is not int or payload[key] <= 0
                       for key in (provider, 'qualityProfileId'))):
            raise ArrImportError('import_payload_invalid')
        if PurePosixPath(_canonical(payload['path'])).parent != PurePosixPath(_canonical(payload['rootFolderPath'])):
            raise ArrImportError('import_payload_invalid')
        if self.service == 'sonarr' and (payload['monitorNewItems'] != 'none'
                or not isinstance(payload['seasons'], list)
                or any(not isinstance(s, dict) or s.get('monitored') is not False for s in payload['seasons'])):
            raise ArrImportError('import_payload_invalid')
        return self._request('POST', self.resource, payload)
