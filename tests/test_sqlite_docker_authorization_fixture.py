"""Private AuthZ transport regression tests; no Docker daemon access."""
from contextlib import contextmanager
import http.client
import json
from pathlib import Path
import socket
import socketserver
import tempfile
import threading

import pytest
from scripts.sqlite_docker_authorization_fixture import Handler, dispatch, unique_object
from app.sqlite_docker_maintenance_hold import create_disposable_hold, held_disposable_hold


@pytest.mark.parametrize('path', ['/AuthZPlugin.AuthZReq', '/AuthZPlugin.AuthZRes'])
def test_actual_engine_envelope_is_normalized_without_owner_bypass(path):
    assert dispatch(path, {'RequestMethod':'GET', 'RequestUri':'/_ping'})['Allow'] is True
    assert dispatch(path, {'RequestMethod':'POST', 'RequestUri':'/containers/create', 'User':'root'})['Allow'] is False
    assert dispatch(path, {'RequestMethod':'GET', 'RequestUri':'/_ping', 'RequestURI':'/info'})['Allow'] is False
    assert dispatch(path, {'RequestMethod':'GET', 'RequestURI':'/info'})['Allow'] is False


@contextmanager
def endpoint():
    with tempfile.TemporaryDirectory(prefix='mca-auth-', dir='/tmp') as folder:
        path = str(Path(folder).resolve() / 'private.sock')
        root = Path(folder).resolve()
        (root / '.disposable_authorization').write_bytes(b'DISPOSABLE ONLY\n')
        create_disposable_hold(root)
        with held_disposable_hold(root) as verify, socketserver.UnixStreamServer(path, Handler) as server:
            server.verify_hold = verify
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                yield path
            finally:
                server.shutdown()
                thread.join(timeout=5)


class Client(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__('private', timeout=5)
        self.path = path
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.settimeout(5)
        self.sock.connect(self.path)


@pytest.mark.parametrize('route,body,expected', [
    ('/Plugin.Activate', b'', {'Implements':['authz']}),
    ('/AuthZPlugin.AuthZReq', b'{"RequestMethod":"GET","RequestUri":"/_ping"}', {'Allow':True}),
    ('/AuthZPlugin.AuthZReq', b'{"RequestMethod":"POST","RequestUri":"/containers/create"}', {'Allow':False}),
    ('/AuthZPlugin.AuthZReq', b'{"RequestUri":"/info","RequestUri":"/_ping"}', {'Allow':False}),
    ('/AuthZPlugin.AuthZReq', b'invalid-json', {'Allow':False}),
    ('/AuthZPlugin.AuthZReq', b'[]', {'Allow':False}),
    ('/unknown', b'{}', {'Allow':False}),
])
def test_private_http_transport(route, body, expected):
    with endpoint() as path:
        client = Client(path)
        try:
            client.request('POST', route, body=body)
            response = client.getresponse()
            result = json.loads(response.read())
            assert response.status == 200
            for key,value in expected.items():
                assert result[key] == value
        finally:
            client.close()


def test_duplicate_objects_are_rejected():
    with pytest.raises(ValueError):
        json.loads('{"a":1,"a":2}', object_pairs_hook=unique_object)


def test_live_hold_corruption_denies_observations_and_activation():
    with pytest.raises(RuntimeError):  # Closing the held binding also rejects drift.
        with endpoint() as path:
            (Path(path).parent/'maintenance.hold').write_bytes(b'corrupt')
            for route,body in [('/Plugin.Activate',b''), ('/AuthZPlugin.AuthZReq',
                b'{"RequestMethod":"GET","RequestUri":"/_ping"}')]:
                client=Client(path)
                try:
                    client.request('POST',route,body=body)
                    result=json.loads(client.getresponse().read())
                    assert result['Allow'] is False
                    assert 'Implements' not in result
                finally: client.close()


def test_real_fixture_process_can_reload_deny_hold_without_rewriting_it():
    import subprocess
    import sys
    import time
    with tempfile.TemporaryDirectory(prefix='mca-reload-',dir='/tmp') as folder:
        root=Path(folder).resolve()/'control'
        command=[sys.executable,'-B','-m','scripts.sqlite_docker_authorization_fixture','--root',str(root)]
        def start(resume=False):
            process=subprocess.Popen(command+(['--resume-fixture'] if resume else []),
                stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            return process
        def ready(process):
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                if process.poll() is not None:
                    pytest.fail(process.stderr.read().decode(errors='replace'))
                client=Client(str(root/'authorization.sock'))
                try:
                    client.request('POST','/Plugin.Activate',body=b'')
                    assert json.loads(client.getresponse().read())=={'Implements':['authz']}
                    return
                except (OSError,http.client.HTTPException):
                    time.sleep(.05)
                finally: client.close()
            pytest.fail('Fixture startup timed out')
        process=start()
        try:
            ready(process)
            before={p.name:p.read_bytes() for p in root.iterdir() if p.is_file()}
            duplicate=subprocess.run(command+['--resume-fixture'],capture_output=True,timeout=5)
            assert duplicate.returncode!=0
            assert b'Another authorization fixture is active' in duplicate.stderr
            ready(process)  # Rejected adoption did not unlink the live socket.
            process.kill(); process.wait(timeout=5); process.stderr.close()
            process=start(True)
            ready(process)
            assert before=={p.name:p.read_bytes() for p in root.iterdir() if p.is_file()}
        finally:
            if process.poll() is None: process.kill()
            process.wait(timeout=5)
            process.stderr.close()
