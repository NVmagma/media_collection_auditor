"""Exclusive advisory lock for offline migration coordination.

This lock only coordinates cooperating migration processes. Production JSON
writers do not acquire it, so stop all auditor instances before migration.
"""

from __future__ import annotations

from contextlib import contextmanager
import os
from contextvars import ContextVar
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


_held_state_locks: ContextVar[frozenset[str]] = ContextVar(
    "held_state_locks", default=frozenset()
)


@contextmanager
def audit_run_lock(source: str | Path):
    """Hold the shared lock for an entire audit, including nested saves."""
    source = Path(source)
    key = str(source.resolve())
    if key in _held_state_locks.get():
        raise RuntimeError("Nested auditor runs are not permitted")
    with state_writer_lock(source):
        token = _held_state_locks.set(_held_state_locks.get() | {key})
        try:
            yield
        finally:
            _held_state_locks.reset(token)


@contextmanager
def state_writer_lock(source: str | Path):
    """Serialize cooperating JSON saves against offline migration.

    The lock file is persistent: never unlink it after releasing flock, since
    another process may already be waiting on the same inode.
    """
    if fcntl is None:
        raise RuntimeError("JSON state locking requires POSIX flock")
    source = Path(source)
    if str(source.resolve()) in _held_state_locks.get():
        yield  # The current audit already holds the same exclusive lock.
        return
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
