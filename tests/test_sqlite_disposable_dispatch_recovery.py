import json

import pytest

from app import sqlite_disposable_offline_dispatch as dispatch
from app import sqlite_disposable_dispatch_recovery as recovery
from scripts.sqlite_offline_dispatch_guest_lab import prepare


@pytest.fixture
def installed(tmp_path,monkeypatch):
    root=prepare(tmp_path.resolve()/'fixture')
    monkeypatch.setattr(dispatch,'_scope',lambda:('boot','net:[1]','mnt:[2]'))
    monkeypatch.setattr(dispatch,'_unique_mount_id',lambda path:1000)
    rows={}
    calls=[]
    monkeypatch.setattr(dispatch,'_mount_rows',lambda:tuple(rows.values()) or (('1','0','0:1','/','/','rw'),))
    def mount(command,**kwargs):
        calls.append(command)
        target=dispatch.Path(command[-1])
        if command[1]=='--bind':
            target.unlink();target.write_bytes(dispatch.GUARD)
            rows[str(target)]=(str(len(rows)+10),'1','0:1','/guard',str(target),'rw')
        else:
            row=rows[str(target)]
            rows[str(target)]=(*row[:5],'ro,nosuid,nodev')
    monkeypatch.setattr(dispatch.subprocess,'run',mount)
    return root,rows,calls


def test_installer_receipts_integrate_with_locked_recovery_review(installed):
    root,rows,calls=installed
    with dispatch.install_disposable_offline_dispatch(root):
        assert len(list(root.glob('installed-*.json')))==6
        with pytest.raises(RuntimeError,match='Controller lock held'):
            recovery.review_disposable_controller_recovery(root)
    before={p:p.read_bytes() for p in root.glob('*.json')}
    result=recovery.review_disposable_controller_recovery(root)
    assert set(result['mount_evidence'].values())=={'request_bound_guard_mount_observed'}
    assert sum(b.startswith('hidden_original_unverified:') for b in result['blockers'])==6
    assert result['restoration_authorized'] is False
    assert result['controller_adoption_authorized'] is False
    assert {p:p.read_bytes() for p in root.glob('*.json')}==before
    assert len(calls)==12


def test_identical_guard_replacement_mount_is_not_owned(installed):
    root,rows,_=installed
    with dispatch.install_disposable_offline_dispatch(root):pass
    target=str(root/'host/usr/local/sbin/mover')
    rows[target]=('999',*rows[target][1:])
    with pytest.raises(RuntimeError,match='Owned guard mount changed'):
        dispatch.verify_disposable_offline_dispatch(root)
    result=recovery.review_disposable_controller_recovery(root)
    assert result['mount_evidence']['mover']=='receipt_mount_conflict'
    assert 'receipt_mount_conflict:mover' in result['blockers']


def test_receipt_cannot_be_replayed_against_changed_request(installed):
    root,_,_=installed
    with dispatch.install_disposable_offline_dispatch(root):pass
    path=root/'pending-request.json'
    request=json.loads(path.read_bytes())
    request['originals']['mover']['sha256']='0'*64
    path.write_text(json.dumps(request))
    with pytest.raises(RuntimeError,match='Invalid owned-mount receipt'):
        recovery.review_disposable_controller_recovery(root)


def test_partial_bind_without_receipt_remains_uncertain(installed,monkeypatch):
    root,_,calls=installed
    actual=dispatch.subprocess.run
    def interrupted(command,**kwargs):
        actual(command,**kwargs)
        raise RuntimeError('controller terminated after bind')
    monkeypatch.setattr(dispatch.subprocess,'run',interrupted)
    with pytest.raises(RuntimeError,match='terminated'):
        with dispatch.install_disposable_offline_dispatch(root):pass
    result=recovery.review_disposable_controller_recovery(root)
    assert result['mount_evidence']['rc.docker']=='unreceipted_mount'
    assert 'unreceipted_mount:rc.docker' in result['blockers']
    assert len(calls)==1


def test_missing_controller_lock_is_not_repaired(installed):
    root,_,_=installed
    with dispatch.install_disposable_offline_dispatch(root):pass
    (root/'controller.lock').unlink()
    with pytest.raises(FileNotFoundError):recovery.review_disposable_controller_recovery(root)
    assert not (root/'controller.lock').exists()


def test_receipt_fsync_failure_stops_installation_with_mount_retained(installed,monkeypatch):
    root,rows,calls=installed
    actual=recovery.os.fsync
    syncs=0
    def fail(fd):
        nonlocal syncs
        syncs+=1
        # request file+directory, then first receipt file.
        if syncs==3:raise OSError('receipt sync failed')
        actual(fd)
    monkeypatch.setattr(recovery.os,'fsync',fail)
    with pytest.raises(OSError,match='receipt sync failed'):
        with dispatch.install_disposable_offline_dispatch(root):pass
    assert len(calls)==2 and len(rows)==1
    assert (root/'pending-request.json').exists()


@pytest.mark.parametrize('change',[
    lambda r:r.update(schema_version=True),
    lambda r:r.update(route='rc.nfsd'),
    lambda r:r.update(production_authorized=True),
    lambda r:r.update(mount=['bad']),
    lambda r:r.update(extra='unexpected'),
])
def test_invalid_receipt_never_becomes_recovery_evidence(installed,change):
    root,_,_=installed
    with dispatch.install_disposable_offline_dispatch(root):pass
    path=root/recovery.receipt_name('mover')
    receipt=json.loads(path.read_bytes());change(receipt)
    path.write_text(json.dumps(receipt))
    before=path.read_bytes()
    with pytest.raises(RuntimeError,match='Invalid owned-mount receipt'):
        recovery.review_disposable_controller_recovery(root)
    assert path.read_bytes()==before


def test_changed_boot_does_not_adopt_matching_receipts(installed,monkeypatch):
    root,_,_=installed
    with dispatch.install_disposable_offline_dispatch(root):pass
    monkeypatch.setattr(dispatch,'_scope',lambda:('different-boot','net:[1]','mnt:[2]'))
    result=recovery.review_disposable_controller_recovery(root)
    assert set(result['mount_evidence'].values())=={'receipt_scope_changed'}
    assert 'controller_scope_changed' in result['blockers']
    assert result['controller_adoption_authorized'] is False


def test_receipt_change_during_review_rejected(installed,monkeypatch):
    root,_,_=installed
    with dispatch.install_disposable_offline_dispatch(root):pass
    actual=recovery.read_installed_mount
    def drift(directory,route,pending):
        result=actual(directory,route,pending)
        if route=='mover':
            path=root/recovery.receipt_name(route)
            path.write_bytes(path.read_bytes()+b' ')
        return result
    monkeypatch.setattr(recovery,'read_installed_mount',drift)
    with pytest.raises(RuntimeError,match='Controller recovery binding changed'):
        recovery.review_disposable_controller_recovery(root)


def test_orphan_receipt_blocks_install_before_request(installed):
    root,_,calls=installed
    (root/recovery.receipt_name('mover')).write_text('{}')
    with pytest.raises(RuntimeError,match='Retained mount receipt'):
        with dispatch.install_disposable_offline_dispatch(root):pass
    assert not (root/'pending-request.json').exists() and not calls


def test_reused_mountinfo_id_does_not_hide_unique_mount_change(installed,monkeypatch):
    root,_,_=installed
    with dispatch.install_disposable_offline_dispatch(root):pass
    target=root/'host/usr/local/sbin/mover'
    monkeypatch.setattr(dispatch,'_unique_mount_id',lambda path:2000 if path==target else 1000)
    with pytest.raises(RuntimeError,match='Owned guard mount changed'):
        dispatch.verify_disposable_offline_dispatch(root)
    result=recovery.review_disposable_controller_recovery(root)
    assert result['mount_evidence']['mover']=='receipt_mount_conflict'


@pytest.mark.parametrize('mask,identity,result',[(0,123,0),(0x1000,123,0),(0x4000,0,0),(0x4000,123,-1)])
def test_statx_unknown_capability_never_falls_back(monkeypatch,mask,identity,result):
    import struct
    class Function:
        def __call__(self,fd,path,flags,wanted,data):
            assert wanted==0x4000 and flags==0x100
            struct.pack_into('=I',data,0,mask)
            struct.pack_into('=Q',data,144,identity)
            return result
    class Library:statx=Function()
    monkeypatch.setattr(recovery.ctypes,'CDLL',lambda *a,**k:Library())
    with pytest.raises(RuntimeError,match='Unique mount identity unavailable'):
        recovery.unique_mount_id('/fixture/target')


def test_statx_supported_unique_identity(monkeypatch):
    import struct
    class Function:
        def __call__(self,fd,path,flags,wanted,data):
            struct.pack_into('=I',data,0,0x4000)
            struct.pack_into('=Q',data,144,2**32+5)
            return 0
    class Library:statx=Function()
    monkeypatch.setattr(recovery.ctypes,'CDLL',lambda *a,**k:Library())
    assert recovery.unique_mount_id('/fixture/target')==2**32+5


def test_unique_mount_capability_missing_prevents_install_intent(installed,monkeypatch):
    root,_,calls=installed
    def fail(path):raise RuntimeError('Unique mount identity unavailable')
    monkeypatch.setattr(dispatch,'_unique_mount_id',fail)
    with pytest.raises(RuntimeError,match='Unique mount identity unavailable'):
        with dispatch.install_disposable_offline_dispatch(root):pass
    assert not (root/'pending-request.json').exists() and not calls
