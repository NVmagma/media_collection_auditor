"""Accidental-target guards only; real-writer acceptance runs in the QEMU guest."""
from pathlib import Path
from types import SimpleNamespace
import pytest
from scripts import sqlite_docker_writer_guest_lab as guest
from app.sqlite_docker_quiesce_policy import authorize_quiesce_request


@pytest.mark.parametrize('runtime_probe', [False, True])
@pytest.mark.parametrize('platform,uid,hostname', [('darwin',501,'Mac'),('linux',0,'Tower'),('linux',1000,'mca-writer-fixture')])
def test_other_hosts_rejected_before_files_or_process_controls(monkeypatch,tmp_path,platform,uid,hostname,runtime_probe):
    monkeypatch.setattr(guest.sys,'platform',platform)
    monkeypatch.setattr(guest.os,'geteuid',lambda:uid)
    monkeypatch.setattr(guest.socket,'gethostname',lambda:hostname)
    monkeypatch.setattr(guest.subprocess,'run',lambda *a,**k:pytest.fail('No process operations'))
    root=tmp_path/'absent'
    with pytest.raises(RuntimeError,match='never run on Tower'):
        guest.run(root,tmp_path/'bin',tmp_path/'image',probe_runtime_route=runtime_probe)
    assert not root.exists()


def test_existing_guest_daemon_blocks_without_stopping_it(monkeypatch,tmp_path):
    monkeypatch.setattr(guest.sys,'platform','linux')
    monkeypatch.setattr(guest.os,'geteuid',lambda:0)
    monkeypatch.setattr(guest.socket,'gethostname',lambda:'mca-writer-fixture')
    monkeypatch.setattr(Path,'read_text',lambda *a,**k:'mca-writer-fixture')
    commands=[]
    def existing(args,**kwargs):
        commands.append(args)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(guest.subprocess,'run',existing)
    root=tmp_path/'absent'
    with pytest.raises(RuntimeError,match='Existing daemon'):
        guest.run(root,tmp_path/'bin',tmp_path/'image')
    assert commands==[['pgrep','-x','dockerd']]
    assert not root.exists()


def test_only_selected_full_id_inspection_is_added():
    identity='a'*64
    request={'RequestMethod':'GET','RequestURI':f'/containers/{identity}/json'}
    assert authorize_quiesce_request(request,(identity,))['Allow'] is True
    assert authorize_quiesce_request(request,())['Allow'] is False
    request['RequestMethod']='POST'
    assert authorize_quiesce_request(request,(identity,))['Allow'] is False
