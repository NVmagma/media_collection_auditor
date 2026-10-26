import hashlib
import pytest
from app import sqlite_disposable_nfs_backend as backend

GUARD=b'FIXTURE DENY BYTES\n'


@pytest.fixture
def lab(tmp_path,monkeypatch):
    (tmp_path/'.disposable_nfs_guard').write_bytes(backend.MARKER)
    for name in ('persistent.cfg','runtime.ini'):(tmp_path/name).write_bytes(b'shareNFSEnabled="no"\n')
    for name in ('dispatch-a','dispatch-b'):(tmp_path/name).write_bytes(GUARD)
    monkeypatch.setattr(backend,'_kernel_state',lambda:('boot','net','mnt'))
    monkeypatch.setattr(backend,'_guard_mounts',lambda root:('guard-a','guard-b'))
    return tmp_path


def observer(root):
    return backend.held_disposable_nfs_observer(root=root,guard_sha256=hashlib.sha256(GUARD).hexdigest())


def test_complete_fixture_observation_returns_no_permit(lab):
    with observer(lab) as verify:assert verify() is None


@pytest.mark.parametrize('name',['persistent.cfg','runtime.ini'])
def test_enabled_preference_cannot_be_admitted(lab,name):
    (lab/name).write_bytes(b'shareNFSEnabled="yes"\n')
    with pytest.raises(RuntimeError,match='not explicitly disabled'):
        with observer(lab):pass


@pytest.mark.parametrize('drift',['kernel','mount','preference','guard'])
def test_changed_binding_latches_denial(lab,monkeypatch,drift):
    with observer(lab) as verify:
        if drift=='kernel':monkeypatch.setattr(backend,'_kernel_state',lambda:('other','net','mnt'))
        elif drift=='mount':monkeypatch.setattr(backend,'_guard_mounts',lambda root:('replacement',))
        elif drift=='preference':(lab/'persistent.cfg').write_bytes(b'shareNFSEnabled="no"\nother=changed\n')
        else:(lab/'dispatch-a').write_bytes(b'CHANGED\n')
        with pytest.raises(RuntimeError):verify()
        with pytest.raises(RuntimeError,match='retained review'):verify()


def test_missing_guard_mount_is_not_replaced_by_zero_threads(lab,monkeypatch):
    def unavailable(root):raise RuntimeError('guard mounts unavailable')
    monkeypatch.setattr(backend,'_guard_mounts',unavailable)
    with pytest.raises(RuntimeError,match='guard mounts'):
        with observer(lab):pass


def test_guest_rehearsal_refuses_running_service_without_controls(monkeypatch,tmp_path):
    from scripts import sqlite_nfs_backend_guest_lab as lab
    monkeypatch.setattr(lab,'require_guest',lambda:None)
    def running():raise RuntimeError('NFS server threads not stopped')
    monkeypatch.setattr(lab,'_kernel_state',running)
    monkeypatch.setattr(lab.subprocess,'run',lambda *a,**k:pytest.fail('No controls'))
    root=tmp_path/'absent'
    with pytest.raises(RuntimeError,match='not stopped'):lab.run(root)
    assert not root.exists()
