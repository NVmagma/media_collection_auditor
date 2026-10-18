"""Exclusive advisory lock for offline migration coordination.

This lock only coordinates cooperating migration processes. Production JSON
writers do not acquire it, so stop all auditor instances before migration.
"""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - Unraid runs Linux
    fcntl = None


@contextmanager
def migration_lock(source: str | Path):
    """Hold an exclusive nonblocking lock adjacent to the JSON state file."""
    if fcntl is None:
        raise RuntimeError("Offline migration locking requires POSIX flock")
    source = Path(source)
    lock_path = source.with_name(source.name + ".migration.lock")
    if not source.is_file():
        raise RuntimeError("Source JSON state is missing; refusing migration")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another offline migration holds the state lock") from exc
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


@contextmanager
def state_writer_lock(source: str | Path):
    """Serialize cooperating JSON saves against offline migration.

    The lock file is persistent: never unlink it after releasing flock, since
    another process may already be waiting on the same inode.
    """
    if fcntl is None:
        raise RuntimeError("JSON state locking requires POSIX flock")
    source = Path(source)
    lock_path = source.with_name(source.name + ".migration.lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("JSON state write blocked by another state operation") from exc
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
