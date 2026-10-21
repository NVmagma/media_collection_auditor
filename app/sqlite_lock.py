"""Exclusive advisory lock for offline migration coordination.

Current JSON writers and offline migration share this advisory lock. Older
instances and external writers may not cooperate: stop them before migration.
"""

from __future__ import annotations

from contextlib import contextmanager
import os
from contextvars import ContextVar
from pathlib import Path
import stat

try:
    import fcntl
except ImportError:  # pragma: no cover - Unraid runs Linux
    fcntl = None


class StateLockBusy(RuntimeError):
    """A cooperating process already owns the shared state lock."""


@contextmanager
def migration_lock(source: str | Path):
    """Hold an exclusive nonblocking lock adjacent to the JSON state file."""
    if fcntl is None:
        raise RuntimeError("Offline migration locking requires POSIX flock")
    source = Path(source)
    lock_path = source.with_name(source.name + ".migration.lock")
    if not source.is_file():
        raise RuntimeError("Source JSON state is missing; refusing migration")
    with _exclusive_lock(lock_path, "Another offline migration holds the state lock"):
        yield


@contextmanager
def _exclusive_lock(lock_path, contention_message):
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        held = os.fstat(fd)
        if not stat.S_ISREG(held.st_mode) or held.st_nlink != 1:
            raise RuntimeError("Unsafe state lock file")
        def verify():
            current = os.stat(lock_path, follow_symlinks=False)
            pinned = os.fstat(fd)
            if (not stat.S_ISREG(current.st_mode) or current.st_nlink != 1
                    or pinned.st_nlink != 1
                    or (current.st_dev, current.st_ino) != (held.st_dev, held.st_ino)):
                raise RuntimeError("State lock binding changed")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise StateLockBusy(contention_message) from exc
        try:
            verify()
            yield verify
            verify()
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


_held_state_locks: ContextVar[dict] = ContextVar("held_state_locks", default={})


@contextmanager
def audit_run_lock(source: str | Path):
    """Hold the shared lock for an entire audit, including nested saves."""
    source = Path(source)
    key = str(source.resolve())
    if key in _held_state_locks.get():
        raise RuntimeError("Nested auditor runs are not permitted")
    with state_writer_lock(source) as verify:
        token = _held_state_locks.set({**_held_state_locks.get(), key: verify})
        try:
            yield verify
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
    held_check = _held_state_locks.get().get(str(source.resolve()))
    if held_check is not None:
        held_check()
        yield held_check  # The current audit already holds this exclusive lock.
        held_check()
        return
    lock_path = source.with_name(source.name + ".migration.lock")
    with _exclusive_lock(lock_path, "JSON state write blocked by another state operation") as verify:
        yield verify
