import json

import pytest

from scripts import sqlite_host_controller_container_lab as lab


@pytest.mark.parametrize('native',[False,True])
def test_fixture_cannot_target_an_existing_service_or_inherit_host_access(monkeypatch,native):
    image='sha256:'+'a'*64;container='b'*64;calls=[]
    def command(*args,**kwargs):
        calls.append(args)
        if args[:3]==('docker','image','inspect'):
            return json.dumps([{'Id':image,'Config':{'Volumes':None}}]).encode()
        if args[:2]==('docker','create'):return container.encode()
        if args[:2]==('docker','start'):raise RuntimeError('fixture failure')
        return b''
    monkeypatch.setattr(lab,'command',command)
    with pytest.raises(RuntimeError,match='fixture failure'):lab.run(image,native=native)
    create=next(args for args in calls if args[:2]==('docker','create'))
    assert '--mount' not in create and '--volume' not in create and '--cap-add' not in create
    assert '--privileged' not in create and '--read-only' in create
    assert create[create.index('--network')+1]=='none'
    assert create[create.index('--cap-drop')+1]=='ALL'
    assert calls[-1]==('docker','rm','--force',container)


def test_fixture_requires_immutable_image_before_docker_contact(monkeypatch):
    monkeypatch.setattr(lab,'command',lambda *a,**k:pytest.fail('No Docker contact'))
    with pytest.raises(ValueError):lab.run('python:latest')
