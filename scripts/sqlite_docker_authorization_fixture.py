"""Private always-maintenance AuthZ endpoint for disposable daemon tests only.

No daemon connection, host installation, policy off-switch or service controls.
"""
import argparse
from http.server import BaseHTTPRequestHandler
import json
import os
import stat
from pathlib import Path
import socketserver

from app.sqlite_docker_maintenance_policy import authorize_maintenance_request
from app.sqlite_docker_quiesce_policy import authorize_quiesce_request
from app.sqlite_docker_maintenance_hold import create_disposable_hold, held_disposable_hold, _read_at

LIMIT = 65536
DENY = {'Allow': False, 'Msg': 'Maintenance request denied', 'Err': ''}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def dispatch(path, value, *, container_ids=()):
    if path == '/Plugin.Activate':
        return {'Implements': ['authz']}
    if path in ('/AuthZPlugin.AuthZReq', '/AuthZPlugin.AuthZRes'):
        if not isinstance(value, dict) or 'RequestUri' not in value or 'RequestURI' in value:
            return DENY
        normalized = dict(value)
        normalized['RequestURI'] = normalized.pop('RequestUri')
        if 'RequestHeaders' not in normalized and 'RequestHeader' not in normalized:
            normalized['RequestHeader'] = {}  # Engine omits empty header maps.
        quiesce = authorize_quiesce_request(normalized, container_ids)
        return quiesce if quiesce['Allow'] else authorize_maintenance_request(normalized)
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
            verify = getattr(self.server, 'verify_hold', None)
            if verify is None:
                raise RuntimeError('Durable hold unavailable')
            verify()
            result = dispatch(self.path, value, container_ids=verify.quiesce_container_ids)
            verify()
        except (ValueError, TypeError, UnicodeError, TimeoutError, OSError, RuntimeError):
            result = DENY
        body = json.dumps(result).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--quiesce-container-id', action='append', default=[])
    parser.add_argument('--resume-fixture', action='store_true',
                        help='Reload existing deny-only hold; never release writers')
    args = parser.parse_args()
    root = Path(args.root)
    if not root.is_absolute() or root.resolve() != root:
        raise RuntimeError('Canonical new fixture root required')
    if not args.resume_fixture:
        root.mkdir(mode=0o700)  # Exclusive initialization; partial state is retained.
        with (root / '.disposable_authorization').open('xb') as marker:
            marker.write(b'DISPOSABLE ONLY\n')
            marker.flush()
            os.fsync(marker.fileno())
        create_disposable_hold(root, container_ids=args.quiesce_container_id)
    if args.resume_fixture and args.quiesce_container_id:
        raise RuntimeError('Reload cannot override persisted container scope')
    with held_disposable_hold(root) as verify:
        endpoint = root / 'authorization.sock'
        if os.path.lexists(endpoint):
            if not args.resume_fixture or not stat.S_ISSOCK(endpoint.lstat().st_mode):
                raise RuntimeError('Unsafe retained fixture endpoint')
            verify()  # Held persistent lock excludes another cooperating listener.
            endpoint.unlink()
        spec = root / 'plugin.spec'
        expected_spec = 'unix://' + str(endpoint)
        if args.resume_fixture:
            directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                _read_at(directory, 'plugin.spec', expected_spec.encode())
            finally:
                os.close(directory)
            verify()
        else:
            with spec.open('x') as output:
                output.write(expected_spec)
                output.flush()
                os.fsync(output.fileno())
        with socketserver.UnixStreamServer(str(endpoint), Handler) as server:
            server.verify_hold = verify
            server.timeout = 1
            server.serve_forever()



if __name__ == '__main__':
    main()
