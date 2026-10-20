"""Single-writer runner for marked disposable SQLite rehearsals only.

This is not a production executor. The lock excludes cooperating runners,
not Arr, manual filesystem writers, mount changes or other databases.
"""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat

from app.sqlite_disposable_lifecycle_flow import execute_disposable_lifecycle_move
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.state_store import GuardedSQLiteStateStore


@contextmanager
def isolated_runner_lock(root):
    """Hold one persistent lock inode across the entire disposable operation."""
    root = Path(root)
    marker = root / ".sqlite_disposable_rehearsal"
    database = root / "state.db"
    if (not root.is_absolute() or root.resolve() != root or root.is_symlink()
            or not root.is_dir() or marker.is_symlink() or not marker.is_file()
            or marker.read_text() != "DISPOSABLE ONLY\n"
            or database.is_symlink() or not database.is_file()):
        raise RuntimeError("Marked disposable root and database required")
    directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    lock_fd = None
    try:
        lock_fd = os.open(".sqlite_runner.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
                          0o600, dir_fd=directory_fd)
        info = os.fstat(lock_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RuntimeError("Unsafe disposable runner lock")
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another isolated SQLite runner is active") from None
        expected = os.fstat(directory_fd)
        current = os.stat(root, follow_symlinks=False)
        if (expected.st_dev, expected.st_ino) != (current.st_dev, current.st_ino):
            raise RuntimeError("Disposable root changed before execution")
        yield
        current = os.stat(root, follow_symlinks=False)
        if (expected.st_dev, expected.st_ino) != (current.st_dev, current.st_ino):
            raise RuntimeError("Disposable root changed during execution")
    finally:
        # Never unlink: waiters must continue to refer to the same lock inode.
        if lock_fd is not None:
            os.close(lock_fd)
        os.close(directory_fd)


def run_isolated_lifecycle_move(*, root, database, **operation):
    """Stop on pending intent before entering the existing disposable executor.

    Exceptions propagate; no retry, recovery clearance or automatic replay.
    Existing same-filesystem rename, witness and CAS guards remain mandatory.
    """
    root, database = Path(root), Path(database)
    if database != root / "state.db":
        raise RuntimeError("Disposable runner database binding mismatch")
    with isolated_runner_lock(root):
        snapshot, revision = GuardedSQLiteStateStore(database).load_with_revision()
        if INTENTS_KEY in snapshot:
            raise RuntimeError("Unresolved SQLite operation; isolated runner stopped")
        expected = operation.pop("expected_revision", revision)
        if expected != revision:
            raise RuntimeError("Stale isolated runner revision")
        return execute_disposable_lifecycle_move(
            root=root, database=database, expected_revision=expected,
            _use_directory_handles=True, **operation)
