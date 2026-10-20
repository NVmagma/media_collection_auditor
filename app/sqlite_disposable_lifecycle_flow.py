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
from app.sqlite_noreplace_rename import (rename_directory_noreplace,
                                        rename_directory_noreplace_at)
from app.sqlite_disposable_parent_witness import (pinned_stage_directories,
    assert_stage_directories_unchanged)
from app.sqlite_disposable_move_runner import STAGES
from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_operation_coordinator import SQLiteOperationCoordinator
from app.sqlite_lifecycle_checkpoint_plan import CLOCKS
from app.sqlite_stale_plan_review import review_plan_again
from app.sqlite_recovery_fingerprint import capture_directory_fingerprint
from app.state_store import GuardedSQLiteStateStore
from app.sqlite_title_identity import validate_title_folder

TRANSITIONS = {
    ("transient", "holding"), ("transient", "keep"),
    ("holding", "removal"), ("holding", "keep"), ("removal", "keep"),
}


def execute_disposable_lifecycle_move(*, root, database, operation_id, media_key,
                                      source_stage="transient",
                                      destination_stage="holding",
                                      observed_at=None, fault_at=None, expected_revision=None,
                                      planned_move=None, _use_directory_handles=False,
                                      _verify_runner_binding=None, title_folder="Movie",
                                      _before_intent_review=None):
    """Persist intent, rename with live witness, checkpoint clocks and intent.

    fault_at is test-only: after_intent, after_rename, after_applied.
    An interrupted run never attempts a second move or clears its intent.
    """
    validate_title_folder(title_folder)
    if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 0):
        raise ValueError("Invalid expected SQLite revision")
    if planned_move is not None:
        if not isinstance(planned_move, dict) or expected_revision is None:
            raise ValueError("Disposable planned move requires expected revision")
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
    if (not isinstance(observed_at, datetime) or observed_at.tzinfo is not None
            or observed_at > datetime.now()):
        raise RuntimeError("Invalid lifecycle observation time; move blocked")
    paths = {}
    for stage in STAGES:
        stage_dir = root / stage
        if stage_dir.is_symlink() or not stage_dir.is_dir():
            raise RuntimeError("Unsafe disposable stage")
        paths[stage] = stage_dir / title_folder
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
                                    fault_at, source, destination, fd, parents,
                                    expected_revision, planned_move, _use_directory_handles,
                                    _verify_runner_binding, title_folder, _before_intent_review)


def _perform_pinned_move(root, database, operation_id, media_key,
                         source_stage, destination_stage, observed_at,
                         fault_at, source, destination, fd, parents,
                         expected_revision, planned_move, use_directory_handles, verify_runner_binding, title_folder, before_intent_review):
    if verify_runner_binding is not None:
        verify_runner_binding()
    original = os.fstat(fd)
    current = os.stat(source, follow_symlinks=False)
    if (original.st_dev, original.st_ino) != (current.st_dev, current.st_ino):
        raise RuntimeError("Source changed before intent")
    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    if expected_revision is not None and session.revision != expected_revision:
        raise RuntimeError("Stale disposable plan revision; no intent or move performed")
    if planned_move is not None:
        try:
            original_plan = planned_move["plan"]
            thresholds = planned_move["thresholds"]
            signals = planned_move["signals_by_key"]
            planned_at = planned_move["now"]
        except (KeyError, TypeError) as exc:
            raise ValueError("Incomplete disposable planned move") from exc
        if original_plan.get("source_revision") != expected_revision:
            raise RuntimeError("Disposable plan revision binding mismatch")
        review = review_plan_again(
            database=database, original_plan=original_plan,
            now=planned_at, thresholds=thresholds, signals_by_key=signals,
            favorites_trigger_keep=planned_move.get("favorites_trigger_keep", True))
        if review["status"] != "unchanged_advisory_only":
            raise RuntimeError("Disposable plan changed; no intent or move performed")
        mapping = {"transient": "Waiting", "holding": "Holding",
                   "removal": "Removal", "keep": "Keep"}
        matching = [row for row in original_plan["rows"]
                    if row["media_key"] == media_key]
        if (len(matching) != 1
                or matching[0]["source_stage"] != mapping[source_stage]
                or matching[0]["destination_stage"] != mapping[destination_stage]
                or matching[0]["status"] != "candidate_requires_verification"):
            raise RuntimeError("Disposable plan does not match requested move")
        # This is parity rehearsal only: supplied Jellyfin data is not trusted.
    # Refuse an invalid source clock before persisting intent or renaming.
    # Reconciliation performs the same check again after the witnessed move.
    stage_name = {"transient": "Waiting", "holding": "Holding",
                  "removal": "Removal", "keep": "Keep"}[source_stage]
    source_clock = CLOCKS[stage_name]
    persisted, _ = session.read_verified_snapshot()
    if media_key not in persisted[source_clock]:
        raise RuntimeError("Source lifecycle clock unavailable; move blocked")
    if any(media_key in persisted[section] for section in CLOCKS.values()
           if section != source_clock):
        raise RuntimeError("Conflicting lifecycle clocks; move blocked")
    if observed_at < datetime.fromisoformat(persisted[source_clock][media_key]):
        raise RuntimeError("Lifecycle observation predates source clock; move blocked")
    clock_binding = {
        "source_stage": source_stage, "destination_stage": destination_stage,
        "source_timestamp": persisted[source_clock][media_key],
        "observed_at": observed_at.isoformat(),
    }
    if verify_runner_binding is not None:
        verify_runner_binding()
    if before_intent_review is not None:
        before_intent_review()
        assert_stage_directories_unchanged(root, parents)
        if verify_runner_binding is not None:
            verify_runner_binding()
    coordinator = SQLiteOperationCoordinator(session)
    coordinator.begin_move_with_evidence(
        operation_id, {"media_key": media_key,
                       "source": str(source), "destination": str(destination),
                       "lifecycle_clock_binding": clock_binding})
    assert_stage_directories_unchanged(root, parents)
    if verify_runner_binding is not None:
        verify_runner_binding()
    if fault_at == "after_intent":
        raise RuntimeError("Injected crash after intent")
    # The persisted intent is durable before this external operation.
    try:
        if use_directory_handles:
            current = os.stat(title_folder, dir_fd=parents[source_stage], follow_symlinks=False)
            if (original.st_dev, original.st_ino) != (current.st_dev, current.st_ino):
                raise RuntimeError("Source changed before descriptor-bound rename")
            rename_directory_noreplace_at(parents[source_stage], title_folder,
                                         parents[destination_stage], title_folder)
        else:
            rename_directory_noreplace(source, destination)
    except OSError as exc:
        if exc.errno == errno.EXDEV:
            raise RuntimeError("Cross-device move blocked; intent retained") from exc
        raise
    assert_stage_directories_unchanged(root, parents)
    if verify_runner_binding is not None:
        verify_runner_binding()
    if fault_at == "after_rename":
        raise RuntimeError("Injected crash after rename")
    coordinator.mark_applied(operation_id)
    if fault_at == "after_applied":
        raise RuntimeError("Injected crash after applied checkpoint")
    assert_stage_directories_unchanged(root, parents)
    if verify_runner_binding is not None:
        verify_runner_binding()
    return reconcile_witnessed_disposable_rename(
        root=root, database=database, operation_id=operation_id,
        media_key=media_key, source_stage=source_stage,
        destination_stage=destination_stage,
        observed_at=observed_at, witness_fd=fd, require_clock_binding=True,
        title_folder=title_folder)
