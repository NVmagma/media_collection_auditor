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


def check(root, *, plugin_available, hold_invalid=False):
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
    if hold_invalid:
        routes = [('GET', '/_ping', 403), ('POST', '/containers/create', 403)]
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


def check_quiesce_routing(root):
    # Only the empty private daemon fixture is used. This deliberately absent ID
    # tests routing after authorization, NOT a successful stop or policy update.
    root = Path(root)
    check(root, plugin_available=True)
    identity = '0'*64
    scopes = json.loads((root/'control/quiesce.json').read_bytes())
    if scopes != [identity]:
        raise RuntimeError('Dedicated synthetic quiesce scope required')
    raw = b'{"RestartPolicy":{"Name":"no","MaximumRetryCount":0}}'
    statuses=[]
    for method, route, body, headers, expected in [
        ('POST', f'/containers/{identity}/stop', None, {}, 404),
        ('POST', f'/containers/{identity}/update', raw, {'Content-Type':'application/json'}, 404),
        ('POST', f'/containers/{"1"*64}/stop', None, {}, 403),
        ('POST', f'/containers/{identity}/start', None, {}, 403),
        ('POST', f'/containers/{identity}/update', b'{"RestartPolicy":{"Name":"always","MaximumRetryCount":0}}', {'Content-Type':'application/json'}, 403)]:
        client=Client(root/'engine.sock')
        try:
            client.request(method,route,body=body,headers=headers)
            response=client.getresponse()
            response.read(65537)
            if response.status != expected:
                raise RuntimeError('Private quiesce routing result rejected: '+str(response.status))
            statuses.append(response.status)
        finally: client.close()
    return {'http_statuses':statuses, 'existing_writer_verified':False,
            'fixture_only':True, 'production_authorized':False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--plugin-unavailable', action='store_true')
    modes.add_argument('--hold-invalid', action='store_true')
    modes.add_argument('--quiesce-routing', action='store_true')
    args = parser.parse_args()
    print(json.dumps(check_quiesce_routing(args.root) if args.quiesce_routing else
        check(args.root, plugin_available=not args.plugin_unavailable, hold_invalid=args.hold_invalid)))
