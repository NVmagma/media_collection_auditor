import json

import pytest

from app import sqlite_disposable_offline_dispatch as dispatch
from scripts.sqlite_offline_dispatch_guest_lab import prepare


@pytest.fixture
def root(tmp_path,monkeypatch):
    monkeypatch.setattr(dispatch,'_scope',lambda:('boot','net:[1]','mnt:[2]'))
    return prepare(tmp_path.resolve()/'fixture')


def test_durable_request_precedes_every_mount_and_failure_retains_it(root,monkeypatch):
    calls=[]
    def fail(command,**kwargs):
        request=json.loads((root/'pending-request.json').read_bytes())
        assert request['phase']=='fence_requested'
        assert set(request['originals'])==set(dispatch.ROUTES)
        assert request['production_authorized'] is False
        calls.append(command)
        raise RuntimeError('synthetic mount failure')
    monkeypatch.setattr(dispatch.subprocess,'run',fail)
    with pytest.raises(RuntimeError,match='synthetic mount failure'):
        with dispatch.install_disposable_offline_dispatch(root):pytest.fail('No success')
    pending=(root/'pending-request.json').read_bytes()
    with pytest.raises(RuntimeError,match='no reinstall'):
        with dispatch.install_disposable_offline_dispatch(root):pytest.fail('No adoption')
    assert (root/'pending-request.json').read_bytes()==pending
    assert len(calls)==1


@pytest.mark.parametrize('drift',['marker','lock','request','scope'])
def test_binding_loss_after_bind_prevents_next_external_action(root,monkeypatch,drift):
    calls=[]
    def change(command,**kwargs):
        calls.append(command)
        if drift=='marker':(root/'.disposable_offline_dispatch').write_bytes(b'changed')
        elif drift=='request':(root/'pending-request.json').write_bytes(b'changed')
        elif drift=='scope':monkeypatch.setattr(dispatch,'_scope',lambda:('boot','net:[1]','mnt:[3]'))
        else:
            (root/'controller.lock').rename(root/'retained-lock')
            (root/'controller.lock').touch()
    monkeypatch.setattr(dispatch.subprocess,'run',change)
    with pytest.raises(RuntimeError,match='binding changed'):
        with dispatch.install_disposable_offline_dispatch(root):pytest.fail('No success')
    assert len(calls)==1
    assert (root/'pending-request.json').exists()


@pytest.mark.parametrize('failed_sync',[1,2])
def test_failed_request_fsync_never_reaches_mount(root,monkeypatch,failed_sync):
    monkeypatch.setattr(dispatch.subprocess,'run',lambda *a,**k:pytest.fail('No mount'))
    original=dispatch.os.fsync
    calls=0
    def fail(fd):
        nonlocal calls
        calls+=1
        if calls==failed_sync:raise OSError('synthetic fsync failure')
        return original(fd)
    monkeypatch.setattr(dispatch.os,'fsync',fail)
    with pytest.raises(OSError,match='fsync'):
        with dispatch.install_disposable_offline_dispatch(root):pytest.fail('No success')
    assert (root/'pending-request.json').exists()


def test_alias_escape_blocks_before_request(root,tmp_path,monkeypatch):
    (root/'host/etc/rc.d').unlink()
    (root/'host/etc/rc.d').symlink_to(tmp_path)
    monkeypatch.setattr(dispatch.subprocess,'run',lambda *a,**k:pytest.fail('No mount'))
    with pytest.raises(RuntimeError,match='alias binding'):
        with dispatch.install_disposable_offline_dispatch(root):pytest.fail('No success')
    assert not (root/'pending-request.json').exists()


def test_unmarked_root_never_mounts(tmp_path,monkeypatch):
    monkeypatch.setattr(dispatch.subprocess,'run',lambda *a,**k:pytest.fail('No mount'))
    with pytest.raises(FileNotFoundError):
        with dispatch.install_disposable_offline_dispatch(tmp_path.resolve()):pytest.fail('No success')


def test_guest_launcher_refuses_host_before_creating_fixture(tmp_path,monkeypatch):
    from scripts import sqlite_offline_dispatch_guest_lab as lab
    def deny():raise RuntimeError('Dedicated guest required')
    monkeypatch.setattr(lab,'require_guest',deny)
    monkeypatch.setattr(lab.subprocess,'Popen',lambda *a,**k:pytest.fail('No subprocess'))
    root=tmp_path/'absent'
    with pytest.raises(RuntimeError,match='Dedicated guest'):lab.run(root)
    assert not root.exists()


def test_retained_request_with_missing_lock_is_not_repaired(root,monkeypatch):
    pending=root/'pending-request.json'
    pending.write_bytes(b'retained uncertain request')
    before=set(root.iterdir())
    monkeypatch.setattr(dispatch.subprocess,'run',lambda *a,**k:pytest.fail('No mount'))
    with pytest.raises(RuntimeError,match='no reinstall'):
        with dispatch.install_disposable_offline_dispatch(root):pytest.fail('No adoption')
    assert set(root.iterdir())==before
    assert not (root/'controller.lock').exists()
    assert pending.read_bytes()==b'retained uncertain request'


@pytest.mark.parametrize('arguments',[[],['start'],['stop'],['restart'],['reload'],
                                     ['update'],['status'],['unrecognized']])
def test_fixed_guard_denies_samba_default_and_explicit_dispatches(tmp_path,arguments):
    import subprocess
    guard=tmp_path/'deny-guard'
    guard.write_bytes(dispatch.GUARD)
    result=subprocess.run(['/bin/bash','-p',str(guard),*arguments],capture_output=True)
    assert result.returncode==75
    assert result.stdout==b''
    assert b'Offline maintenance service dispatch denied' in result.stderr


def test_every_fixed_route_is_in_fake_host_tree(root):
    targets=dispatch._targets(root)
    assert set(targets)=={'rc.docker','rc.nfsd','rc.samba','mover','mover.old','move-helper'}
    for name,target in targets.items():
        assert root/'host' in target.parents
        assert b'UNGUARDED FIXTURE' in target.read_bytes()
    assert targets['move-helper']==root/'host/usr/libexec/unraid/move'


@pytest.mark.parametrize('change',[
    lambda r:r.update(schema_version=True),
    lambda r:r.update(production_authorized=True),
    lambda r:r.update(writer_exclusion_verified=True),
    lambda r:r.update(unexpected='field'),
    lambda r:r['originals'].pop('mover'),
    lambda r:r['originals']['mover'].update(identity=[True,1,2,3,4]),
    lambda r:r['originals']['mover'].update(sha256='unknown'),
])
def test_invalid_retained_record_rejected_before_mount_observation(root,monkeypatch,change):
    def fail(*args,**kwargs):raise RuntimeError('fixture mount interruption')
    monkeypatch.setattr(dispatch.subprocess,'run',fail)
    with pytest.raises(RuntimeError,match='interruption'):
        with dispatch.install_disposable_offline_dispatch(root):pass
    path=root/'pending-request.json'
    request=json.loads(path.read_bytes())
    assert dispatch._pending_request(path.read_bytes())==request
    change(request)
    path.write_text(json.dumps(request))
    before=path.read_bytes()
    monkeypatch.setattr(dispatch,'_mounts',lambda *a:pytest.fail('No mount observation'))
    with pytest.raises(RuntimeError,match='Invalid retained fixture request'):
        dispatch.verify_disposable_offline_dispatch(root)
    assert path.read_bytes()==before


def test_duplicate_nested_request_key_is_rejected():
    with pytest.raises(RuntimeError,match='Invalid retained fixture request'):
        dispatch._pending_request(b'{"originals":{"mover":1,"mover":2}}')
