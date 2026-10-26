import socket
import tempfile
from pathlib import Path
import pytest
from app import sqlite_disposable_docker_backend as backend

IDENTITY='a'*64


@pytest.fixture
def fixture(tmp_path,monkeypatch):
    temporary=tempfile.TemporaryDirectory(prefix='mca-dock-',dir='/tmp')
    root=Path(temporary.name).resolve()
    (root/'.disposable_writer').write_bytes(b'DISPOSABLE ONLY\n')
    endpoint=socket.socket(socket.AF_UNIX)
    endpoint.bind(str(root/'engine.sock'))
    calls=[]
    def request(path,route,timeout):
        calls.append(route)
        if route=='/info':
            return {'ID':'fixture-daemon','LiveRestoreEnabled':False,'Plugins':{'Authorization':['fixture-policy']}}
        return {'Id':IDENTITY,'State':{'Running':False,'Paused':False,'Restarting':False,
            'Dead':False,'Status':'exited','Pid':0},
            'HostConfig':{'RestartPolicy':{'Name':'no','MaximumRetryCount':0}}}
    monkeypatch.setattr(backend,'_request',request)
    yield root,calls,request
    endpoint.close()
    temporary.cleanup()


def observe(root):
    return backend.held_disposable_docker_observer(root=root,daemon_id='fixture-daemon',
        plugin='fixture-policy',container_ids=[IDENTITY])


def test_reads_only_explicit_identity_and_status(fixture):
    root,calls,_=fixture
    with observe(root) as verify:
        assert verify() is None
    assert calls==['/info','/containers/'+IDENTITY+'/json']


@pytest.mark.parametrize('drift',['daemon','policy','live_restore','running'])
def test_live_drift_latches_denial(fixture,monkeypatch,drift):
    root,calls,original=fixture
    def changed(*args):
        value=original(*args)
        if args[1]=='/info':
            if drift=='daemon':value['ID']='different'
            if drift=='policy':value['Plugins']['Authorization']=[]
            if drift=='live_restore':value['LiveRestoreEnabled']=True
        elif drift=='running':value['State']['Running']=True
        return value
    monkeypatch.setattr(backend,'_request',changed)
    with observe(root) as verify:
        with pytest.raises((RuntimeError,ValueError)):verify()
        monkeypatch.setattr(backend,'_request',original)
        before=list(calls)
        with pytest.raises(RuntimeError,match='review required'):verify()
        assert calls==before


def test_socket_replacement_never_adopted(fixture):
    root,calls,_=fixture
    replacement=socket.socket(socket.AF_UNIX)
    try:
        with observe(root) as verify:
            (root/'engine.sock').rename(root/'retained.sock')
            replacement.bind(str(root/'engine.sock'))
            with pytest.raises(RuntimeError,match='binding changed'):verify()
        assert calls==[]
    finally:replacement.close()


def test_binding_rechecked_after_network_call(fixture,monkeypatch):
    root,_,original=fixture
    def replace_marker(*args):
        value=original(*args)
        (root/'.disposable_writer').rename(root/'retained.marker')
        (root/'.disposable_writer').write_bytes(b'DISPOSABLE ONLY\n')
        return value
    monkeypatch.setattr(backend,'_request',replace_marker)
    with observe(root) as verify:
        with pytest.raises(RuntimeError):verify()


def test_empty_scope_cannot_mean_no_writers(tmp_path):
    with pytest.raises(ValueError,match='Explicit fixture'):
        with backend.held_disposable_docker_observer(root=tmp_path,daemon_id='fixture',
                plugin='policy',container_ids=[]):pass


def test_transport_timeout_is_redacted_and_stays_failed(fixture,monkeypatch):
    root,_,original=fixture
    def timeout(*args):raise TimeoutError('private transport detail')
    monkeypatch.setattr(backend,'_request',timeout)
    with observe(root) as verify:
        with pytest.raises(RuntimeError,match='review required') as error:verify()
        assert 'private transport detail' not in str(error.value)
        monkeypatch.setattr(backend,'_request',original)
        with pytest.raises(RuntimeError,match='boundary failed'):verify()
