"""Kernel mount observations are local, strict and never recovery authority."""
import os
import sys

import pytest

import app.sqlite_rename_mount_binding as module


@pytest.mark.parametrize("contents", ["", "pos: 0\n", "mnt_id: -1", "mnt_id: 0",
    "mnt_id: x", "mnt_id: １２", "mnt_id: 10\nmnt_id: 10"])
def test_invalid_or_duplicate_mount_ids_block(contents):
    with pytest.raises(RuntimeError):
        module.parse_fd_mount_id(contents)


def test_valid_descriptor_mount_id():
    assert module.parse_fd_mount_id("pos:\t0\nflags:\t0100000\nmnt_id:\t123\n") == 123


@pytest.fixture
def directories(tmp_path):
    descriptors = []
    for name in ("source", "destination", "witness"):
        path = tmp_path / name
        path.mkdir()
        descriptors.append(os.open(path, os.O_RDONLY | os.O_DIRECTORY))
    try:
        yield descriptors
    finally:
        for fd in descriptors:
            os.close(fd)


def test_same_device_different_mount_ids_are_rejected(directories, monkeypatch):
    monkeypatch.setattr(module, "read_mount_namespace_identity", lambda: (1, 2))
    monkeypatch.setattr(module, "read_fd_mount_id", lambda fd: 10 if fd == directories[0] else 11)
    with pytest.raises(RuntimeError, match="one observed mount"):
        module.capture_rename_mount_binding(*directories)


def test_changed_namespace_or_mount_is_rejected(directories, monkeypatch):
    monkeypatch.setattr(module, "read_mount_namespace_identity", lambda: (1, 2))
    monkeypatch.setattr(module, "read_fd_mount_id", lambda fd: 10)
    binding = module.capture_rename_mount_binding(*directories)
    module.assert_rename_mount_binding(binding, *directories)
    monkeypatch.setattr(module, "read_mount_namespace_identity", lambda: (1, 3))
    with pytest.raises(RuntimeError, match="binding changed"):
        module.assert_rename_mount_binding(binding, *directories)
    monkeypatch.setattr(module, "read_mount_namespace_identity", lambda: (1, 2))
    monkeypatch.setattr(module, "read_fd_mount_id", lambda fd: 11)
    with pytest.raises(RuntimeError, match="binding changed"):
        module.assert_rename_mount_binding(binding, *directories)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux /proc required")
def test_real_kernel_descriptor_mount_binding(directories):
    binding = module.capture_rename_mount_binding(*directories)
    assert len({item["mount_id"] for item in binding["directories"]}) == 1
    module.assert_rename_mount_binding(binding, *directories)
