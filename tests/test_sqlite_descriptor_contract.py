"""Test syscall arguments and fail-closed behavior without requiring Linux."""
import ctypes
import errno
import os
from types import SimpleNamespace

import pytest

import app.sqlite_noreplace_rename as module


@pytest.mark.parametrize("error", [0, errno.ENOSYS, errno.EXDEV])
def test_descriptor_syscall_arguments_and_no_fallback(tmp_path, monkeypatch, error):
    calls = []
    class Rename:
        def __call__(self, *args):
            calls.append(args)
            ctypes.set_errno(error)
            return -1 if error else 0
    monkeypatch.setattr(module.sys, "platform", "linux")
    monkeypatch.setattr(module.ctypes, "CDLL", lambda *a, **kw: SimpleNamespace(renameat2=Rename()))
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        if error:
            with pytest.raises((RuntimeError, OSError)):
                module.rename_directory_noreplace_at(fd, "Movie", fd, "Target")
        else:
            module.rename_directory_noreplace_at(fd, "Movie", fd, "Target")
        assert calls == [(fd, b"Movie", fd, b"Target", 1)]
        assert list(tmp_path.iterdir()) == []
    finally:
        os.close(fd)
