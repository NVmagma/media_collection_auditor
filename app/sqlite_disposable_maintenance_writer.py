"""Cooperative fixture writer for maintenance acceptance; NOT an NFS fence.

Only this writer honors the fixture journal. Other processes, open descriptors
and services are not constrained by it. There is no production caller.
"""
from contextlib import contextmanager
import os
import stat

from app.sqlite_disposable_maintenance_journal import (
    _database, _history, _root, _require_no_client_writeback_hold,
)


def _writable(db):
    _require_no_client_writeback_hold(db)
    if _history(db)[-1][1] not in {"prepared", "released"}:
        raise RuntimeError("Disposable writer fenced by pending maintenance")


def _identity(info):
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise RuntimeError("Unsafe disposable writer file")
    return info.st_dev, info.st_ino


class _FixtureWriter:
    def __init__(self, root, fd):
        self.root, self.fd = root, fd
        self.identity = _identity(os.fstat(fd))

    def write(self, payload):
        if not isinstance(payload, bytes) or not 1 <= len(payload) <= 1024:
            raise ValueError("Fixture writes require 1..1024 bytes")
        with _database(self.root, with_verifier=True) as (db, verify):
            _writable(db)
            if (_identity(os.fstat(self.fd)) != self.identity
                    or _identity((self.root / "writer.fixture").lstat()) != self.identity):
                raise RuntimeError("Disposable writer binding changed")
            verify()
            if os.write(self.fd, payload) != len(payload):
                raise RuntimeError("Partial disposable write; inspect retained fixture")
            os.fsync(self.fd)
            verify()


@contextmanager
def open_disposable_writer(root):
    """Open one fixed lab file; recheck maintenance for EVERY write, even on old FDs."""
    root = _root(root)
    fd = None
    try:
        with _database(root) as db:
            _writable(db)
            fd = os.open(root / "writer.fixture",
                         os.O_CREAT | os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK,
                         0o600)
            writer = _FixtureWriter(root, fd)
        yield writer
    finally:
        if fd is not None:
            os.close(fd)
