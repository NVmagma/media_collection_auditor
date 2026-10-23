"""Filesystem identities are real; unavailable Mac proc readers simulated."""
import sys

import pytest

from app import sqlite_disposable_storage_backend as module


@pytest.fixture
def root(tmp_path, monkeypatch):
    path = tmp_path.resolve() / 'media'
    path.mkdir()
    (path / '.sqlite_disposable_rehearsal').write_bytes(b'DISPOSABLE ONLY\n')
    for name in ('transient', 'holding', 'keep', 'removal'):
        (path / name).mkdir()
    if sys.platform != 'linux':
        monkeypatch.setattr(module, 'read_fd_mount_id', lambda fd: 123)
        monkeypatch.setattr(module, 'read_mount_namespace_identity', lambda: (1, 2))
    return path


def test_healthy_and_closed_observer(root):
    with module.held_disposable_storage_observer(root=root) as verify:
        assert verify() is None
        (root / 'holding' / 'new-title').mkdir()
        assert verify() is None  # Contents are deliberately not frozen.
    with pytest.raises(RuntimeError, match='closed or failed'):
        verify()


@pytest.mark.parametrize('name', ['transient', 'holding', 'keep', 'removal'])
def test_replaced_stage_latches_failure(root, name):
    with module.held_disposable_storage_observer(root=root) as verify:
        (root / name).rename(root / 'retained')
        (root / name).mkdir()
        with pytest.raises(RuntimeError):
            verify()
        (root / name).rmdir()
        (root / 'retained').rename(root / name)
        with pytest.raises(RuntimeError, match='failed'):
            verify()


def test_mount_or_namespace_drift(root, monkeypatch):
    with module.held_disposable_storage_observer(root=root) as verify:
        monkeypatch.setattr(module, 'read_fd_mount_id', lambda fd: 99999999)
        with pytest.raises(RuntimeError):
            verify()
    with module.held_disposable_storage_observer(root=root) as verify:
        monkeypatch.setattr(module, 'read_mount_namespace_identity', lambda: (-1, -1))
        with pytest.raises(RuntimeError):
            verify()


def test_marker_replacement(root):
    with module.held_disposable_storage_observer(root=root) as verify:
        marker = root / '.sqlite_disposable_rehearsal'
        marker.rename(root / 'retained-marker')
        marker.write_bytes(b'DISPOSABLE ONLY\n')
        with pytest.raises(RuntimeError):
            verify()


def test_root_replacement(root):
    with module.held_disposable_storage_observer(root=root) as verify:
        root.rename(root.with_name('retained-root'))
        root.mkdir()
        with pytest.raises(RuntimeError):
            verify()


def test_root_replaced_during_capture(root, monkeypatch):
    original_open = module.os.open
    root_opens = 0
    def replacing_open(path, *args, **kwargs):
        nonlocal root_opens
        if str(path) == str(root):
            root_opens += 1
            if root_opens == 2:
                root.rename(root.with_name('retained-root'))
                root.mkdir()
                (root / '.sqlite_disposable_rehearsal').write_bytes(b'DISPOSABLE ONLY\n')
                for name in ('transient', 'holding', 'keep', 'removal'):
                    (root / name).mkdir()
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(module.os, 'open', replacing_open)
    with pytest.raises(RuntimeError, match='during capture'):
        with module.held_disposable_storage_observer(root=root):
            pytest.fail('Changed capture admitted')


def test_guest_rehearsal_rejects_non_guest_before_creating_paths(tmp_path, monkeypatch):
    from scripts import sqlite_storage_backend_guest_lab as lab
    def deny():
        raise RuntimeError('Dedicated guest required')
    monkeypatch.setattr(lab, 'require_guest', deny)
    monkeypatch.setattr(lab.subprocess, 'run', lambda *a, **k: pytest.fail('No mount controls'))
    target = tmp_path / 'absent'
    with pytest.raises(RuntimeError, match='Dedicated guest'):
        lab.run(target)
    assert not target.exists()
