"""Bounded GET-only Jellyfin transport for scheduled read-only collection.

No redirects, proxy inheritance, automatic retries, response cache or mutating
routes. Never expose token, server URL or raw transport exceptions in errors.
"""
import json
from http.client import HTTPException
import math
import re
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class ScheduledTransportError(RuntimeError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        fp.close()
        raise ScheduledTransportError('redirect_rejected')


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_json_key')
        result[key] = value
    return result


class ScheduledJellyfinGET:
    """Callable read transport; construct per run, not as a cached signal store."""
    def __init__(self, *, base_url, token, timeout_seconds=10, maximum_bytes=8 * 1024 * 1024,
                 maximum_requests=10000):
        try:
            parsed = urlsplit(base_url)
            valid = (parsed.scheme in ('http', 'https') and parsed.hostname and not parsed.username
                     and not parsed.password and not parsed.query and not parsed.fragment)
            parsed.port
        except (ValueError, TypeError):
            valid = False
        if (not valid or not isinstance(base_url, str) or any(ord(c) <= 32 for c in base_url)
                or not isinstance(token, str) or not token
                or any(ord(c) < 33 or ord(c) == 127 or c in ('"', chr(92)) for c in token)):
            raise ValueError('Valid Jellyfin base URL and token required')
        if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
                or not 0 < timeout_seconds <= 60 or type(maximum_bytes) is not int
                or not 1 <= maximum_bytes <= 8 * 1024 * 1024
                or type(maximum_requests) is not int or not 1 <= maximum_requests <= 10000):
            raise ValueError('Invalid read transport limits')
        self._base = base_url.rstrip('/')
        self._token = token
        self._timeout = timeout_seconds
        self._maximum_bytes = maximum_bytes
        self._maximum_requests = maximum_requests
        self._requests = 0
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    def __repr__(self):
        return '<ScheduledJellyfinGET redacted>'

    def __call__(self, path, params):
        if not isinstance(path, str) or not (path == '/Users' or re.fullmatch(r'/Users/[A-Za-z0-9_-]+/Items', path)):
            raise ScheduledTransportError('route_rejected')
        allowed = {'Recursive', 'IncludeItemTypes', 'ExcludeItemTypes', 'CollapseBoxSetItems', 'Fields', 'StartIndex', 'Limit'}
        if params is not None and (not isinstance(params, dict) or not set(params).issubset(allowed)
                or any(type(v) not in (str, int) for v in params.values())):
            raise ScheduledTransportError('query_rejected')
        if self._requests >= self._maximum_requests:
            raise ScheduledTransportError('request_limit_exceeded')
        self._requests += 1
        url = self._base + path + ('?' + urlencode(params) if params else '')
        request = Request(url, method='GET', headers={'X-Emby-Token': self._token,
            'Authorization': 'MediaBrowser Token="' + self._token + '"',
            'Accept': 'application/json', 'Cache-Control': 'no-cache', 'Pragma': 'no-cache'})
        started = monotonic()
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                if response.status != 200:
                    raise ScheduledTransportError('http_response_rejected')
                data = bytearray()
                while True:
                    chunk = response.read1(min(65536, self._maximum_bytes + 1 - len(data)))
                    if monotonic() - started >= self._timeout:
                        raise ScheduledTransportError('response_deadline_exceeded')
                    data.extend(chunk)
                    if len(data) > self._maximum_bytes:
                        raise ScheduledTransportError('response_size_exceeded')
                    if not chunk:
                        break
                return json.loads(data.decode('utf-8'), object_pairs_hook=_object,
                    parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite_json')))
        except ScheduledTransportError:
            raise
        except HTTPError as exc:
            exc.close()
            raise ScheduledTransportError('http_response_rejected') from None
        except (URLError, OSError, HTTPException):
            raise ScheduledTransportError('transport_unavailable') from None
        except (ValueError, UnicodeError):
            raise ScheduledTransportError('invalid_json') from None
