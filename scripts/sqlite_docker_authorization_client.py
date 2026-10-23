"""Bounded HTTP checks against a marked private daemon socket only."""
import argparse
import http.client
import json
from pathlib import Path
import socket
import stat


class Client(http.client.HTTPConnection):
    def __init__(self, endpoint):
        super().__init__('private', timeout=35)
        self.endpoint = endpoint

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.settimeout(35)
        self.sock.connect(str(self.endpoint))


def check(root, *, plugin_available):
    root = Path(root)
    if not root.is_absolute() or root.resolve() != root:
        raise RuntimeError('Canonical fixture root required')
    marker = root / 'control/.disposable_authorization'
    if marker.is_symlink() or marker.read_bytes() != b'DISPOSABLE ONLY\n':
        raise RuntimeError('Private authorization fixture required')
    endpoint = root / 'engine.sock'
    if not stat.S_ISSOCK(endpoint.lstat().st_mode):
        raise RuntimeError('Private Engine socket required')
    routes = ([('GET', '/_ping', 200), ('GET', '/version', 200),
               ('GET', '/containers/json', 200), ('POST', '/containers/create', 403),
               ('POST', '/containers/no-such-fixture/start', 403)]
              if plugin_available else [('POST', '/containers/create', 500)])
    statuses = []
    for method, route, expected in routes:
        client = Client(endpoint)
        try:
            client.request(method, route)
            response = client.getresponse()
            body = response.read(65537)
            if len(body) > 65536 or response.status != expected:
                raise RuntimeError('Private daemon authorization result rejected')
            if not plugin_available and b'plugin' not in body.lower():
                raise RuntimeError('Plugin failure not established')
            if route == '/containers/json' and json.loads(body) != []:
                raise RuntimeError('Private daemon inventory not empty')
            statuses.append(response.status)
        finally:
            client.close()
    return {'http_statuses': statuses, 'fixture_only': True,
            'production_authorized': False, 'restart_inhibition_verified': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--plugin-unavailable', action='store_true')
    args = parser.parse_args()
    print(json.dumps(check(args.root, plugin_available=not args.plugin_unavailable)))
