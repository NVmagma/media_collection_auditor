"""End-to-end SQLite lifecycle rehearsal; disposable directories ONLY.

Never enable this module in the production auditor. No automatic restart
recovery, cross-device copy, deletion, or Arr/Jellyfin side effects.
"""

from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime
import errno
import os
from pathlib import Path

from app.sqlite_disposable_atomic_reconcile import reconcile_witnessed_disposable_rename
from app.sqlite_noreplace_rename import rename_directory_noreplace
from app.sqlite_disposable_parent_witness import (pinned_stage_directories,
    assert_stage_directories_unchanged)
from app.sqlite_disposable_move_runner import STAGES
from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_operation_coordinator import SQLiteOperationCoordinator
from app.sqlite_recovery_fingerprint import capture_directory_fingerprint
from app.state_store import GuardedSQLiteStateStore

TRANSITIONS = {
    ("transient", "holding"), ("transient", "keep"),
    ("holding", "removal"), ("holding", "keep"), ("removal", "keep"),
}


def execute_disposable_lifecycle_move(*, root, database, operation_id, media_key,
                                      source_stage="transient",
                                      destination_stage="holding",
                                      observed_at=None, fault_at=None):
    """Persist intent, rename with live witness, checkpoint clocks and intent.

    fault_at is test-only: after_intent, after_rename, after_applied.
    An interrupted run never attempts a second move or clears its intent.
    """
    root, database = Path(root), Path(database)
    if (not root.is_absolute() or root.is_symlink() or not root.is_dir()
            or root.resolve() != root or database != root / "state.db"
            or database.is_symlink()):
        raise RuntimeError("Disposable root/database mismatch")
    marker = root / ".sqlite_disposable_rehearsal"
    if (marker.is_symlink() or not marker.is_file()
            or marker.read_text() != "DISPOSABLE ONLY\n"):
        raise RuntimeError("Disposable marker missing")
    if ((source_stage, destination_stage) not in TRANSITIONS
            or source_stage not in STAGES or destination_stage not in STAGES):
        raise RuntimeError("Unsupported lifecycle transition")
    if fault_at not in (None, "after_intent", "after_rename", "after_applied"):
        raise ValueError("Unknown fault injection boundary")
    if not isinstance(media_key, str) or not media_key:
        raise RuntimeError("Invalid media key")
    if observed_at is None:
        observed_at = datetime.now()
    paths = {}
    for stage in STAGES:
        stage_dir = root / stage
        if stage_dir.is_symlink() or not stage_dir.is_dir():
            raise RuntimeError("Unsafe disposable stage")
        paths[stage] = stage_dir / "Movie"
    source, destination = paths[source_stage], paths[destination_stage]
    if any(path.exists() or path.is_symlink() for stage, path in paths.items()
           if stage != source_stage):
        raise RuntimeError("Ambiguous title locations")
    if (capture_directory_fingerprint(str(source)).get("status") != "captured"
            or capture_directory_fingerprint(str(destination)).get("status") != "missing"):
        raise RuntimeError("Unsafe source or destination")
    # No cross-device fallback: copy/delete requires a different trust model.
    if os.stat(source.parent).st_dev != os.stat(destination.parent).st_dev:
        raise RuntimeError("Cross-device moves unsupported")
    with ExitStack() as stack:
        parents = stack.enter_context(pinned_stage_directories(root, STAGES))
        fd = os.open(source, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                     | getattr(os, "O_NOFOLLOW", 0))
        stack.callback(os.close, fd)
        return _perform_pinned_move(root, database, operation_id, media_key,
                                    source_stage, destination_stage, observed_at,
                                    fault_at, source, destination, fd, parents)


def _perform_pinned_move(root, database, operation_id, media_key,
                         source_stage, destination_stage, observed_at,
                         fault_at, source, destination, fd, parents):
    original = os.fstat(fd)
    current = os.stat(source, follow_symlinks=False)
    if (original.st_dev, original.st_ino) != (current.st_dev, current.st_ino):
        raise RuntimeError("Source changed before intent")
    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    coordinator = SQLiteOperationCoordinator(session)
    coordinator.begin_move_with_evidence(
        operation_id, {"media_key": media_key,
                       "source": str(source), "destination": str(destination)})
    assert_stage_directories_unchanged(root, parents)
    if fault_at == "after_intent":
        raise RuntimeError("Injected crash after intent")
    # The persisted intent is durable before this external operation.
    try:
        rename_directory_noreplace(source, destination)
    except OSError as exc:
        if exc.errno == errno.EXDEV:
            raise RuntimeError("Cross-device move blocked; intent retained") from exc
        raise
    assert_stage_directories_unchanged(root, parents)
    if fault_at == "after_rename":
        raise RuntimeError("Injected crash after rename")
    coordinator.mark_applied(operation_id)
    if fault_at == "after_applied":
        raise RuntimeError("Injected crash after applied checkpoint")
    assert_stage_directories_unchanged(root, parents)
    return reconcile_witnessed_disposable_rename(
        root=root, database=database, operation_id=operation_id,
        media_key=media_key, source_stage=source_stage,
        destination_stage=destination_stage,
        observed_at=observed_at, witness_fd=fd)
