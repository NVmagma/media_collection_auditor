"""Target/cleanup guards only; actual NFS behavior requires the isolated guest."""
from pathlib import Path
from types import SimpleNamespace
import pytest
from scripts import sqlite_nfs4_guest_lab as guest


@pytest.mark.parametrize('platform,uid,name',[('darwin',501,'Mac'),('linux',0,'Tower'),('linux',1000,'mca-writer-fixture')])
def test_other_hosts_rejected_before_kernel_or_process_controls(monkeypatch,platform,uid,name):
    monkeypatch.setattr(guest.sys,'platform',platform)
    monkeypatch.setattr(guest.os,'geteuid',lambda:uid)
    monkeypatch.setattr(guest.socket,'gethostname',lambda:name)
    monkeypatch.setattr(guest.subprocess,'run',lambda *a,**k:pytest.fail('No process commands'))
    with pytest.raises(RuntimeError,match='never run on Tower'): guest.require_guest()


def simulate_guest(monkeypatch):
    monkeypatch.setattr(guest,'require_guest',lambda:None)


def test_existing_nfs_actor_blocks_before_export_or_module_changes(monkeypatch,tmp_path):
    simulate_guest(monkeypatch)
    calls=[]
    def existing(args,**kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(guest.subprocess,'run',existing)
    monkeypatch.setattr(guest,'command',lambda *a,**k:pytest.fail('No export/kernel command'))
    root=tmp_path/'absent'
    with pytest.raises(RuntimeError,match='Existing guest RPC'): guest.run(root,'4.1')
    assert calls==[['pgrep','-x','rpc.mountd']]
    assert not root.exists()


def test_existing_exports_block_before_lab_creation(monkeypatch,tmp_path):
    simulate_guest(monkeypatch)
    monkeypatch.setattr(guest.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=1))
    monkeypatch.setattr(guest,'command',lambda *a,**k:'existing export')
    root=tmp_path/'absent'
    with pytest.raises(RuntimeError,match='Existing guest exports'): guest.run(root,'4.2')
    assert not root.exists()


def test_existing_server_threads_are_never_stopped_in_cleanup(monkeypatch,tmp_path):
    simulate_guest(monkeypatch)
    calls=[]
    def record(args,**kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr(guest.subprocess,'run',record)
    monkeypatch.setattr(guest,'command',lambda *a,**k:'')
    original=Path.read_text
    def text(path,*args,**kwargs):
        if str(path)=='/proc/fs/nfsd/threads': return '8\n'
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'read_text',text)
    with pytest.raises(RuntimeError,match='Existing guest NFSD threads'):
        guest.run(tmp_path/'lab','4.1')
    assert not any(args[:2]==['rpc.nfsd','0'] for args in calls)


def test_exited_recovery_helper_blocks_acceptance():
    alive=SimpleNamespace(poll=lambda:None)
    exited=SimpleNamespace(poll=lambda:1)
    guest.require_helpers_alive(alive,alive)
    with pytest.raises(RuntimeError,match="helper exited"):
        guest.require_helpers_alive(alive,exited)
