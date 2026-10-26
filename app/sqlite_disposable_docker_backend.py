"""Live selected-writer observer for a marked disposable Docker fixture only.

Read-only API calls. No service control, automatic socket adoption or ownership
permit. The caller must establish the real fence and complete writer scope.
"""
from contextlib import contextmanager
import http.client
import json
import os
from pathlib import Path
import re
import socket
import stat
from time import monotonic

from app.sqlite_docker_maintenance_hold import _read_at, MARKER
from app.sqlite_docker_quiesce_policy import validate_scope, unique_object
from app.sqlite_docker_writer_observation import require_stopped_writer


class _Connection(http.client.HTTPConnection):
    def __init__(self, endpoint, timeout):
        super().__init__('private-fixture', timeout=timeout)
        self.endpoint = endpoint
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.settimeout(self.timeout)
        self.sock.connect(str(self.endpoint))


def _request(endpoint, route, timeout):
    connection = _Connection(endpoint, timeout)
    try:
        connection.request('GET', route)
        response = connection.getresponse()
        content = response.read(1024*1024+1)
        if response.status != 200 or len(content) > 1024*1024:
            raise RuntimeError('Private Docker observation unavailable')
        value = json.loads(content, object_pairs_hook=unique_object)
        if not isinstance(value, dict):
            raise RuntimeError('Private Docker object observation required')
        return value
    finally:
        connection.close()


@contextmanager
def held_disposable_docker_observer(*, root, daemon_id, plugin, container_ids):
    scope = sorted(validate_scope(container_ids))
    if (not scope or not isinstance(daemon_id,str)
            or not re.fullmatch(r'[A-Za-z0-9:_.-]{1,128}',daemon_id)
            or not isinstance(plugin,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',plugin)):
        raise ValueError('Explicit fixture daemon, policy and selected IDs required')
    root = Path(root)
    if not root.is_absolute() or root.resolve()!=root:
        raise ValueError('Canonical marked Docker fixture required')
    directory = os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    endpoint = root/'engine.sock'
    failed = False
    try:
        held = os.fstat(directory)
        marker = _read_at(directory,'.disposable_writer',MARKER)
        def socket_identity():
            info = os.stat('engine.sock',dir_fd=directory,follow_symlinks=False)
            if not stat.S_ISSOCK(info.st_mode):
                raise RuntimeError('Private Docker socket binding unavailable')
            return info.st_dev,info.st_ino
        expected = socket_identity()
        def binding():
            current = root.lstat()
            if (not stat.S_ISDIR(current.st_mode)
                    or (current.st_dev,current.st_ino)!=(held.st_dev,held.st_ino)
                    or _read_at(directory,'.disposable_writer',MARKER)!=marker
                    or socket_identity()!=expected):
                raise RuntimeError('Private Docker fixture binding changed')
        def verify():
            nonlocal failed
            if failed:
                raise RuntimeError('Private Docker boundary failed; review required')
            try:
                binding()
                deadline = monotonic()+5
                def read(route):
                    remaining = deadline-monotonic()
                    if remaining<=0:
                        raise RuntimeError('Private Docker observation window expired')
                    result = _request(endpoint,route,min(remaining,3))
                    binding()
                    if monotonic()>deadline:
                        raise RuntimeError('Private Docker observation window expired')
                    return result
                info = read('/info')
                if (info.get('ID')!=daemon_id or info.get('LiveRestoreEnabled') is not False
                        or not isinstance(info.get('Plugins'),dict)
                        or info['Plugins'].get('Authorization')!=[plugin]):
                    raise RuntimeError('Private Docker daemon/policy observation differs')
                for identity in scope:
                    require_stopped_writer(read('/containers/'+identity+'/json'),identity)
                binding()
            except RuntimeError:
                failed = True
                raise
            except Exception:
                failed = True
                raise RuntimeError('Private Docker observation failed; review required') from None
            except BaseException:
                failed = True
                raise
        yield verify
    finally:
        os.close(directory)
