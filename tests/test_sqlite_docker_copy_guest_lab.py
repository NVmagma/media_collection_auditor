from pathlib import Path
import pytest
from scripts import sqlite_docker_copy_guest_lab as guest


def test_wrong_guest_blocks_before_media_or_journal_access(monkeypatch):
    monkeypatch.setattr(guest, 'require_guest', lambda: (_ for _ in ()).throw(RuntimeError('wrong guest')))
    monkeypatch.setattr(Path, 'read_bytes', lambda *a: pytest.fail('No media reads'))
    monkeypatch.setattr(guest.journal, 'create_disposable_journal', lambda *a, **k: pytest.fail('No journal'))
    with pytest.raises(RuntimeError, match='wrong guest'):
        guest.run_copy_case('/tmp/absent', lambda: pytest.fail('No observer'))


def test_unmarked_writer_blocks_before_creating_copy_tree(monkeypatch, tmp_path):
    monkeypatch.setattr(guest, 'require_guest', lambda: None)
    (tmp_path/'.disposable_writer').write_bytes(b'NOT A LAB\n')
    with pytest.raises(RuntimeError, match='Marked guest writer'):
        guest.run_copy_case(tmp_path, lambda: pytest.fail('No observer'))
    assert sorted(p.name for p in tmp_path.iterdir()) == ['.disposable_writer']


@pytest.mark.parametrize('boundary', ['unknown', '', None])
def test_unknown_loss_boundary_cannot_start_fixture(boundary):
    with pytest.raises(ValueError, match='Known synthetic boundary'):
        guest.run_copy_case('/tmp/absent', lambda: pytest.fail('No observer'), loss_at=boundary)


@pytest.mark.parametrize('same_controller', [True, False])
def test_retry_checker_requires_the_expected_guard_and_unchanged_bytes(monkeypatch, tmp_path, same_controller):
    monkeypatch.setattr(guest, 'require_guest', lambda: None)
    root, control = tmp_path/'media', tmp_path/'control'
    root.mkdir(); control.mkdir()
    (root/'payload').write_bytes(b'original')
    def reject(**kwargs):
        if same_controller:
            raise RuntimeError('Maintenance copy already attempted; review required')
        raise guest.journal.MaintenanceControllerSessionChanged('controller changed')
    monkeypatch.setattr(guest, 'run_maintenance_bound_disposable_copy', reject)
    guest.require_replay_rejected({'root': root, 'journal_root': control}, same_controller=same_controller)
    assert (root/'payload').read_bytes() == b'original'


def test_retry_checker_does_not_accept_unrelated_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(guest, 'require_guest', lambda: None)
    root, control = tmp_path/'media', tmp_path/'control'
    root.mkdir(); control.mkdir()
    def reject(**kwargs):
        raise RuntimeError('unrelated failure')
    monkeypatch.setattr(guest, 'run_maintenance_bound_disposable_copy', reject)
    with pytest.raises(RuntimeError, match='unrelated failure'):
        guest.require_replay_rejected({'root': root, 'journal_root': control})


def test_rejected_retry_must_not_change_retained_bytes(monkeypatch, tmp_path):
    monkeypatch.setattr(guest, 'require_guest', lambda: None)
    root, control = tmp_path/'media', tmp_path/'control'
    root.mkdir(); control.mkdir()
    payload = root/'payload'; payload.write_bytes(b'original')
    def mutate(**kwargs):
        payload.write_bytes(b'changed')
        raise RuntimeError('already attempted')
    monkeypatch.setattr(guest, 'run_maintenance_bound_disposable_copy', mutate)
    with pytest.raises(RuntimeError, match='changed retained bytes'):
        guest.require_replay_rejected({'root': root, 'journal_root': control})
