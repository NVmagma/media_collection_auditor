"""Single-writer runner for marked disposable SQLite rehearsals only.

This is not a production executor. The lock excludes cooperating runners,
not Arr, manual filesystem writers, mount changes or other databases.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import fcntl
import os
from pathlib import Path
import stat

from app.sqlite_disposable_lifecycle_flow import execute_disposable_lifecycle_move
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.state_store import GuardedSQLiteStateStore
from app.sqlite_title_identity import validate_title_folder
from app.sqlite_disposable_planned_executor import validate_disposable_move_candidate


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
    expected_root = os.stat(root, follow_symlinks=False)
    directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    lock_fd = marker_fd = None
    try:
        held_root = os.fstat(directory_fd)
        if (expected_root.st_dev, expected_root.st_ino) != (held_root.st_dev, held_root.st_ino):
            raise RuntimeError("Disposable root changed while opening")
        marker_fd = os.open(".sqlite_disposable_rehearsal",
                            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                            dir_fd=directory_fd)
        held_marker = os.fstat(marker_fd)
        held_database = os.stat("state.db", dir_fd=directory_fd, follow_symlinks=False)
        if (not stat.S_ISREG(held_marker.st_mode) or held_marker.st_nlink != 1
                or not stat.S_ISREG(held_database.st_mode) or held_database.st_nlink != 1):
            raise RuntimeError("Unsafe disposable marker or database")
        marker_content = b"DISPOSABLE ONLY\n"
        if os.pread(marker_fd, len(marker_content) + 1, 0) != marker_content:
            raise RuntimeError("Disposable marker changed while opening")
        lock_fd = os.open(".sqlite_runner.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
                          0o600, dir_fd=directory_fd)
        info = os.fstat(lock_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RuntimeError("Unsafe disposable runner lock")
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another isolated SQLite runner is active") from None

        def verify_binding():
            current = os.stat(root, follow_symlinks=False)
            if (held_root.st_dev, held_root.st_ino) != (current.st_dev, current.st_ino):
                raise RuntimeError("Disposable root changed during execution")
            for name, expected in (("state.db", held_database),
                                   (".sqlite_disposable_rehearsal", held_marker),
                                   (".sqlite_runner.lock", info)):
                current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if (not stat.S_ISREG(current.st_mode) or current.st_nlink != 1
                        or (expected.st_dev, expected.st_ino) !=
                           (current.st_dev, current.st_ino)):
                    raise RuntimeError("Disposable runner binding changed: " + name)
            if os.pread(marker_fd, len(marker_content) + 1, 0) != marker_content:
                raise RuntimeError("Disposable marker contents changed")

        verify_binding()
        yield verify_binding
        verify_binding()
    finally:
        # Never unlink: waiters must continue to refer to the same lock inode.
        if lock_fd is not None:
            os.close(lock_fd)
        if marker_fd is not None:
            os.close(marker_fd)
        os.close(directory_fd)


def run_isolated_lifecycle_move(*, root, database, **operation):
    """Stop on pending intent before entering the existing disposable executor.

    Exceptions propagate; no retry, recovery clearance or automatic replay.
    Existing same-filesystem rename, witness and CAS guards remain mandatory.
    """
    folder = validate_title_folder(operation.get("title_folder", "Movie"))
    if operation.get("media_key") not in (folder, "TV/" + folder):
        raise RuntimeError("Isolated title folder and tracking key mismatch")
    root, database = Path(root), Path(database)
    if database != root / "state.db":
        raise RuntimeError("Disposable runner database binding mismatch")
    with isolated_runner_lock(root) as verify_binding:
        snapshot, revision = GuardedSQLiteStateStore(database).load_with_revision()
        if INTENTS_KEY in snapshot:
            raise RuntimeError("Unresolved SQLite operation; isolated runner stopped")
        expected = operation.pop("expected_revision", revision)
        if expected != revision:
            raise RuntimeError("Stale isolated runner revision")
        verify_binding()
        return execute_disposable_lifecycle_move(
            root=root, database=database, expected_revision=expected,
            _use_directory_handles=True, _verify_runner_binding=verify_binding, **operation)


def run_isolated_planned_move(*, root, database, operation_id, media_key,
                              title_folder="Movie", planned_move,
                              source_stage="transient", destination_stage="holding",
                              observed_at=None, fault_at=None):
    """Require a candidate, then revalidate it inside the locked execution flow.

    The detached bundle is caller-provided advisory evidence, never proof of
    Jellyfin freshness. Production remains disabled and marked labs mandatory.
    """
    bundle = deepcopy(planned_move)
    revision = validate_disposable_move_candidate(
        planned_move=bundle, media_key=media_key, source_stage=source_stage,
        destination_stage=destination_stage)
    planned_at = bundle.get("now")
    if not isinstance(planned_at, datetime) or planned_at.tzinfo is not None:
        raise ValueError("Naive advisory plan time required")
    if observed_at is None:
        observed_at = planned_at
    if observed_at != planned_at:
        raise RuntimeError("Observation differs from advisory plan time; replan required")
    return run_isolated_lifecycle_move(
        root=root, database=database, operation_id=operation_id, media_key=media_key,
        title_folder=title_folder, source_stage=source_stage,
        destination_stage=destination_stage, observed_at=observed_at,
        fault_at=fault_at, expected_revision=revision, planned_move=bundle)
