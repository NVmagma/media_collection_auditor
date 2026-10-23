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


@pytest.mark.parametrize('path', ['/AuthZPlugin.AuthZReq', '/AuthZPlugin.AuthZRes'])
def test_actual_engine_envelope_is_normalized_without_owner_bypass(path):
    assert dispatch(path, {'RequestMethod':'GET', 'RequestUri':'/_ping'})['Allow'] is True
    assert dispatch(path, {'RequestMethod':'POST', 'RequestUri':'/containers/create', 'User':'root'})['Allow'] is False
    assert dispatch(path, {'RequestMethod':'GET', 'RequestUri':'/_ping', 'RequestURI':'/info'})['Allow'] is False
    assert dispatch(path, {'RequestMethod':'GET', 'RequestURI':'/info'})['Allow'] is False


@contextmanager
def endpoint():
    with tempfile.TemporaryDirectory(prefix='mca-auth-', dir='/tmp') as folder:
        path = str(Path(folder) / 'private.sock')
        with socketserver.UnixStreamServer(path, Handler) as server:
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
