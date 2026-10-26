import io
import json
import tarfile

import pytest

from scripts import sqlite_offline_dispatch_container_lab as lab


@pytest.mark.parametrize('image',['latest','python:3.12','sha256:123',''])
def test_mutable_or_incomplete_image_never_contacts_docker(monkeypatch,image):
    monkeypatch.setattr(lab,'command',lambda *a,**k:pytest.fail('No Docker command'))
    with pytest.raises(ValueError,match='Full cached image ID'):
        lab.run(image)


def test_archive_contains_only_python_sources_and_fixed_marker(tmp_path):
    for folder in ('app','scripts'):(tmp_path/folder).mkdir()
    (tmp_path/'app/module.py').write_text('pass')
    (tmp_path/'scripts/token.env').write_text('secret')
    (tmp_path/'sources').mkdir();(tmp_path/'sources/private.py').write_text('secret')
    archive=lab.source_archive(tmp_path)
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
        assert stream.getnames()==['app/module.py','dispatch-container-fixture']
        assert all(member.mode==0o444 for member in stream.getmembers())
    assert b'secret' not in archive


@pytest.mark.parametrize('failure',[False,True])
def test_only_new_container_is_controlled_and_always_removed(monkeypatch,failure):
    image='sha256:'+'a'*64
    container='b'*64
    calls=[]
    def command(*args,**kwargs):
        calls.append((args,kwargs))
        if args[:3]==('docker','image','inspect'):
            return json.dumps([{'Id':image,'Config':{'Volumes':None}}]).encode()
        if args[:2]==('docker','create'):return container.encode()
        if args[:2]==('docker','start'):
            assert kwargs['input']
            if failure:raise RuntimeError('fixture failed')
            return b'fixture passed\n'
        if args[:2]==('docker','inspect'):
            return json.dumps({'ExitCode':0,'OOMKilled':False}).encode()
        return b''
    monkeypatch.setattr(lab,'command',command)
    if failure:
        with pytest.raises(RuntimeError,match='fixture failed'):lab.run(image)
    else:assert lab.run(image)=='fixture passed\n'
    create=next(args for args,_ in calls if args[:2]==('docker','create'))
    assert '--privileged' not in create and '--mount' not in create and '--volume' not in create
    assert create[create.index('--network')+1]=='none'
    assert create[create.index('--cap-drop')+1]=='ALL'
    assert create[create.index('--cap-add')+1]=='SYS_ADMIN'
    assert '--read-only' in create
    assert create[create.index('--tmpfs')+1]=='/fixture:rw,exec,nosuid,nodev,size=32m'
    assert calls[-1][0]==('docker','rm','--force',container)


@pytest.mark.parametrize('inventory',[
    '1 0 0:1 / /fixture rw - ext4 device rw\n',
    '1 0 0:1 / /fixture rw shared:1 - tmpfs tmpfs rw\n',
    '1 0 0:1 / / rw - tmpfs tmpfs rw\n',
])
def test_container_gate_requires_private_tmpfs(monkeypatch,inventory):
    from pathlib import Path
    from scripts import sqlite_offline_dispatch_guest_lab as guest
    monkeypatch.setattr(guest.sys,'platform','linux')
    monkeypatch.setattr(guest.os,'geteuid',lambda:0)
    monkeypatch.setattr(guest.socket,'gethostname',lambda:'mca-dispatch-fixture')
    monkeypatch.setattr(Path,'is_file',lambda self:True)
    monkeypatch.setattr(Path,'read_bytes',lambda self:b'DISPOSABLE DISPATCH CONTAINER ONLY\n')
    monkeypatch.setattr(Path,'read_text',lambda self:inventory)
    with pytest.raises(RuntimeError,match='Private disposable tmpfs'):
        guest.require_dispatch_lab('/fixture/full')


def test_image_declared_volume_rejected_before_create(monkeypatch):
    image='sha256:'+'a'*64
    def command(*args,**kwargs):
        assert args[:3]==('docker','image','inspect')
        return json.dumps([{'Id':image,'Config':{'Volumes':{'/data':{}}}}]).encode()
    monkeypatch.setattr(lab,'command',command)
    with pytest.raises(RuntimeError,match='without declared volumes'):
        lab.run(image)
