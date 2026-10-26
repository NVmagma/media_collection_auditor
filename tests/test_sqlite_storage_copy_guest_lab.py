import pytest

from scripts import sqlite_storage_copy_guest_lab as lab


def test_wrong_environment_never_creates_or_mounts(tmp_path, monkeypatch):
    def reject():
        raise RuntimeError('Dedicated guest required')
    monkeypatch.setattr(lab, 'require_guest', reject)
    monkeypatch.setattr(lab, 'mount', lambda *a: pytest.fail('No mount'))
    monkeypatch.setattr(lab, 'run_copy_case', lambda *a, **k: pytest.fail('No copy'))
    root = tmp_path / 'absent'
    with pytest.raises(RuntimeError, match='Dedicated guest'):
        lab.run(root)
    assert not root.exists()


def test_existing_root_is_never_adopted(tmp_path, monkeypatch):
    monkeypatch.setattr(lab, 'require_guest', lambda: None)
    monkeypatch.setattr(lab, 'mount', lambda *a: pytest.fail('No mount'))
    marker = tmp_path / 'retained'
    marker.write_bytes(b'retained fixture bytes')
    with pytest.raises(FileExistsError):
        lab.run(tmp_path.resolve())
    assert marker.read_bytes() == b'retained fixture bytes'


def test_relative_root_rejected_before_copy(monkeypatch):
    monkeypatch.setattr(lab, 'require_guest', lambda: None)
    monkeypatch.setattr(lab, 'run_copy_case', lambda *a, **k: pytest.fail('No copy'))
    with pytest.raises(ValueError, match='Canonical'):
        lab.run('relative')


@pytest.mark.parametrize('providers', [{'docker': lambda: None}, {'nfs': lambda: None}])
def test_partial_domain_set_rejected_before_fixture_creation(tmp_path, monkeypatch, providers):
    monkeypatch.setattr(lab, 'require_guest', lambda: None)
    root = tmp_path.resolve() / 'absent'
    with pytest.raises(ValueError, match='Both external'):
        lab.run(root, **providers)
    assert not root.exists()


def test_unified_missing_writer_blocks_before_nfs_mounts(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from scripts import sqlite_unified_copy_guest_lab as unified
    monkeypatch.setattr(unified, 'require_guest', lambda: None)
    @contextmanager
    def missing(**kwargs):
        def deny():
            raise RuntimeError('Selected writer unavailable')
        yield deny
    monkeypatch.setattr(unified, 'held_disposable_docker_observer', missing)
    monkeypatch.setattr(unified, 'prepare_guard_fixture',
                        lambda *a: pytest.fail('No mount setup after unavailable writer'))
    docker_root = tmp_path.resolve()
    root = docker_root / 'media' / 'absent'
    with pytest.raises(RuntimeError, match='Selected writer'):
        unified.run(root=root, docker_root=docker_root, daemon_id='fixture',
                    plugin='fixture', container_ids=['a' * 64])
    assert not root.exists()
