"""Offline candidate Docker HTTP maintenance policy; no listener or installer.

Always-maintenance rules only. No inactive mode, administrator bypass, daemon
access or claim of gRPC/automatic-restart/existing-stream enforcement.
"""
from urllib.parse import parse_qsl, urlsplit

MAX_URI = 2048
OBSERVATIONS = {('GET', '/_ping'), ('HEAD', '/_ping'), ('GET', '/version'),
                ('GET', '/info'), ('GET', '/containers/json')}


def authorize_maintenance_request(request):
    """Return Docker AuthZ response shape, without echoing request secrets.

    Version-prefixed routes are deliberately denied pending an installed-engine
    compatibility test. A request lacking the expected complete metadata denies.
    Only the private fixture endpoint calls this policy; a true result is not
    a production permit.
    """
    deny = {'Allow': False, 'Msg': 'Maintenance request denied', 'Err': ''}
    if not isinstance(request, dict):
        return deny
    if 'RequestHeaders' in request and 'RequestHeader' in request:
        return deny
    method, uri = request.get('RequestMethod'), request.get('RequestURI')
    headers = request.get('RequestHeaders')
    if headers is None:
        headers = request.get('RequestHeader')
    if (not isinstance(method, str) or not isinstance(uri, str)
            or not 0 < len(uri) <= MAX_URI or not isinstance(headers, dict)
            or any(ord(char) < 33 or ord(char) > 126 for char in uri)
            or '%' in uri or '#' in uri or uri.endswith('?') or '\\' in uri or not uri.startswith('/') or uri.startswith('//')
            or request.get('RequestBody') not in (None, '')):
        return deny
    for key, values in headers.items():
        if (not isinstance(key, str) or not key.isascii()
                or not key or any(char.isspace() for char in key)
                or not (isinstance(values, str) or (isinstance(values, list)
                    and all(isinstance(v, str) for v in values)))):
            return deny
        # No upgrades, hop-by-hop/tunnel ambiguity, framed body or content body.
        if key.lower() in {'upgrade', 'connection', 'transfer-encoding', 'content-length',
                           'content-type', 'trailer', 'te', 'x-http-method-override'}:
            return deny
    try:
        parsed = urlsplit(uri)
        if parsed.scheme or parsed.netloc or parsed.fragment or (method, parsed.path) not in OBSERVATIONS:
            return deny
        if parsed.query:
            pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True,
                              max_num_fields=1)
            if parsed.path != '/containers/json' or pairs not in ([('all', '0')], [('all', '1')]):
                return deny
    except ValueError:
        return deny
    return {'Allow': True, 'Msg': 'Maintenance observation allowed', 'Err': ''}
