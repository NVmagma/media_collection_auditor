"""Private always-maintenance AuthZ endpoint for disposable daemon tests only.

No daemon connection, host installation, policy off-switch or service controls.
"""
import argparse
from http.server import BaseHTTPRequestHandler
import json
from pathlib import Path
import socketserver

from app.sqlite_docker_maintenance_policy import authorize_maintenance_request

LIMIT = 65536
DENY = {'Allow': False, 'Msg': 'Maintenance request denied', 'Err': ''}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def dispatch(path, value):
    if path == '/Plugin.Activate':
        return {'Implements': ['authz']}
    if path in ('/AuthZPlugin.AuthZReq', '/AuthZPlugin.AuthZRes'):
        if not isinstance(value, dict) or 'RequestUri' not in value or 'RequestURI' in value:
            return DENY
        normalized = dict(value)
        normalized['RequestURI'] = normalized.pop('RequestUri')
        if 'RequestHeaders' not in normalized and 'RequestHeader' not in normalized:
            normalized['RequestHeader'] = {}  # Engine omits empty header maps.
        return authorize_maintenance_request(normalized)
    return DENY


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(3)

    def log_message(self, *args):
        pass  # Never log request payloads/credentials.

    def do_POST(self):
        result = DENY
        try:
            lengths = self.headers.get_all('Content-Length', [])
            if not lengths and self.path == '/Plugin.Activate':
                lengths = ['0']
            if (len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit()
                    or not 0 <= int(lengths[0]) <= LIMIT or self.headers.get('Transfer-Encoding')):
                raise ValueError('Invalid framing')
            data = self.rfile.read(int(lengths[0]))
            if len(data) != int(lengths[0]):
                raise ValueError('Incomplete request')
            value = {} if not data and self.path == '/Plugin.Activate' else json.loads(data, object_pairs_hook=unique_object)
            if not isinstance(value, dict):
                raise ValueError('Object required')
            result = dispatch(self.path, value)
        except (ValueError, TypeError, UnicodeError, TimeoutError):
            pass
        body = json.dumps(result).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    args = parser.parse_args()
    root = Path(args.root)
    if not root.is_absolute() or root.resolve() != root:
        raise RuntimeError('Canonical new fixture root required')
    root.mkdir(mode=0o700)  # Never adopt/replace an existing control root.
    (root / '.disposable_authorization').write_text('DISPOSABLE ONLY\n')
    endpoint = root / 'authorization.sock'
    (root / 'plugin.spec').write_text('unix://' + str(endpoint))
    with socketserver.UnixStreamServer(str(endpoint), Handler) as server:
        server.timeout = 1
        server.serve_forever()


if __name__ == '__main__':
    main()
