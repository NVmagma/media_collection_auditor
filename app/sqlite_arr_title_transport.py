"""One attempt at an Arr title update, with two independent readbacks.

Only a durable-intent caller may invoke this transport. It neither manages nor
clears SQLite intents/queues. No retry, redirects, proxies, delete or moveFiles.
"""
from copy import deepcopy
from http.client import HTTPException
import json
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.request import Request

from app.sqlite_arr_catalog import ArrCatalogGET
from app.sqlite_arr_reconciliation import inspect_arr_sync, validate_arr_sync_details
from app.sqlite_scheduled_paths import _canonical
from app.sqlite_scheduled_transport import _object
from app.sqlite_title_identity import validate_title_folder


class ArrTitleTransportError(RuntimeError):
    pass


class ArrTitleUpdate:
    """Single-use full-resource PUT; receipt and readbacks never clear state.

    The expected source path comes from the bound preparation, not remote title
    search. Other resource fields, including Sonarr seasons, remain unchanged.
    """
    def __init__(self, *, service, base_url, token, source_path, title_folder, verify_binding=None):
        client = ArrCatalogGET(service=service, base_url=base_url, token=token)
        self._url, self._token, self._opener = client._url, client._token, client._opener
        self._service = service
        self._folder = validate_title_folder(title_folder)
        self._source = _canonical(source_path)
        if self._source.rsplit('/', 1)[-1] != self._folder:
            raise ValueError('Bound Arr source folder required')
        if verify_binding is not None and not callable(verify_binding):
            raise ValueError('Callable binding verifier required')
        self._verify = verify_binding or (lambda: None)
        self._used = False

    def __repr__(self):
        return '<ArrTitleUpdate redacted>'

    def _request(self, method, url, deadline, body=None):
        self._verify()
        try:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise ValueError('deadline')
            request = Request(url, method=method, data=body, headers={
                'X-Api-Key': self._token, 'Cache-Control': 'no-cache',
                'Accept': 'application/json', 'Content-Type': 'application/json'})
            with self._opener.open(request, timeout=min(10, remaining)) as response:
                expected = (202,) if method == 'PUT' and self._service == 'radarr' else (200,)
                if response.status not in expected:
                    raise ValueError('status')
                raw = bytearray()
                while True:
                    chunk = response.read1(min(65536, 8 * 1024 * 1024 + 1 - len(raw)))
                    if monotonic() >= deadline:
                        raise ValueError('deadline')
                    raw.extend(chunk)
                    if len(raw) > 8 * 1024 * 1024:
                        raise ValueError('size')
                    if not chunk:
                        break
            def invalid(value):
                raise ValueError('nonfinite')
            record = json.loads(raw, object_pairs_hook=_object, parse_constant=invalid)
            if not isinstance(record, dict):
                raise ValueError('shape')
            self._verify()
            return record
        except HTTPError as error:
            error.close()
            raise ArrTitleTransportError('Arr update/readback unavailable; no retry') from None
        except (URLError, HTTPException, OSError, ValueError, TypeError, RuntimeError):
            raise ArrTitleTransportError('Arr update/readback unavailable; no retry') from None

    def __call__(self, details):
        if self._used:
            raise ArrTitleTransportError('Arr update attempt already used; no retry')
        self._used = True
        request = deepcopy(details)
        validate_arr_sync_details(request)
        if set(request) != {'service', 'title_id', 'root', 'monitored'} or request['service'] != self._service:
            raise ArrTitleTransportError('Bound Arr request required')
        destination = _canonical(request['root'] + '/' + self._folder)
        url = self._url + '/' + str(request['title_id'])
        # One deadline spans the initial read, update and both independent reads.
        deadline = monotonic() + 10
        record = self._request('GET', url, deadline)
        if (type(record.get('id')) is not int or record['id'] != request['title_id']
                or record.get('path') != self._source or type(record.get('monitored')) is not bool):
            raise ArrTitleTransportError('Arr source identity changed; update refused')
        update = deepcopy(record)
        update['path'], update['monitored'] = destination, request['monitored']
        raw = json.dumps(update, allow_nan=False, separators=(',', ':')).encode()
        if len(raw) > 8 * 1024 * 1024:
            raise ArrTitleTransportError('Arr update resource too large')
        # This response acknowledges transport only. Its content proves nothing.
        self._request('PUT', url + '?moveFiles=false', deadline, raw)
        for _ in range(2):
            observed = self._request('GET', url, deadline)
            if (inspect_arr_sync(request, observed) != 'matching_record_unverified'
                    or observed.get('path') != destination):
                raise ArrTitleTransportError('Arr readback mismatch; outcome unresolved')
        return True
