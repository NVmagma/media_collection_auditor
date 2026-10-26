from pathlib import Path
import pytest
from scripts import sqlite_nfs_copy_hold_guest_lab as guest


def test_other_hosts_rejected_before_lab_access(monkeypatch):
    monkeypatch.setattr(guest,'require_guest',lambda: (_ for _ in ()).throw(RuntimeError('wrong guest')))
    monkeypatch.setattr(Path,'read_bytes',lambda *a:pytest.fail('No lab reads'))
    with pytest.raises(RuntimeError,match='wrong guest'):
        guest.prepare_uncertain_copy_hold('/tmp/absent')


def test_unmarked_nfs_lab_is_not_used(monkeypatch,tmp_path):
    monkeypatch.setattr(guest,'require_guest',lambda:None)
    (tmp_path/'.disposable_nfs4').write_bytes(b'NOT A LAB\n')
    with pytest.raises(RuntimeError,match='Marked independent NFS'):
        guest.prepare_uncertain_copy_hold(tmp_path)
    assert not (tmp_path/'data').exists()
