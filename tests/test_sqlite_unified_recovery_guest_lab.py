from contextlib import contextmanager

import pytest

from app import sqlite_disposable_maintenance_journal as journal
from scripts import sqlite_unified_recovery_guest_lab as lab


@pytest.fixture
def retained(tmp_path, monkeypatch):
    media, control = tmp_path/'media', tmp_path/'control'
    media.mkdir(); control.mkdir()
    (media/'original').write_bytes(b'original')
    (control/'attempt').write_bytes(b'pending')
    @contextmanager
    def storage(**kwargs):
        yield lambda: None
    monkeypatch.setattr(lab, 'held_disposable_storage_observer', storage)
    return media, control


@pytest.mark.parametrize('expected,error', [
    ('controller', journal.MaintenanceControllerSessionChanged),
    ('boot', journal.MaintenanceBootScopeChanged)])
def test_exact_scope_rejection_after_fresh_domain_checks(retained,monkeypatch,expected,error):
    media,control=retained
    calls=[]
    def reject(**kwargs):
        assert calls == ['docker','nfs','nfs','docker']
        raise error('changed')
    monkeypatch.setattr(lab,'run_unified_disposable_copy',reject)
    lab.require_rejection(media=media,control=control,expected=expected,
                          docker=lambda:calls.append('docker'),nfs=lambda:calls.append('nfs'))


def test_unrelated_failure_is_not_acceptance(retained,monkeypatch):
    media,control=retained
    def fail(**kwargs):raise RuntimeError('unrelated I/O error')
    monkeypatch.setattr(lab,'run_unified_disposable_copy',fail)
    with pytest.raises(RuntimeError,match='unrelated'):
        lab.require_rejection(media=media,control=control,expected='boot',
                              docker=lambda:None,nfs=lambda:None)


def test_rejection_that_changes_evidence_fails(retained,monkeypatch):
    media,control=retained
    def fail(**kwargs):
        (control/'attempt').write_bytes(b'changed')
        raise journal.MaintenanceControllerSessionChanged('changed')
    monkeypatch.setattr(lab,'run_unified_disposable_copy',fail)
    with pytest.raises(RuntimeError,match='changed retained bytes'):
        lab.require_rejection(media=media,control=control,expected='controller',
                              docker=lambda:None,nfs=lambda:None)


def test_wrong_environment_has_no_controls(tmp_path,monkeypatch):
    def deny():raise RuntimeError('Dedicated guest required')
    monkeypatch.setattr(lab,'require_guest',deny)
    monkeypatch.setattr(lab,'prepare_guard_fixture',lambda *a:pytest.fail('No controls'))
    with pytest.raises(RuntimeError,match='Dedicated guest'):
        lab.run(retained_root=tmp_path,guard_root=tmp_path/'new',docker_root=tmp_path,
                daemon_id='test',plugin='test',container_ids=['a'*64],expected='boot')
    assert not (tmp_path/'new').exists()
