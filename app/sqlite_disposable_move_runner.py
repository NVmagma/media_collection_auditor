"""Explicitly isolated SQLite move rehearsal. NEVER use on production media.

The runner performs a same-device directory rename only under a fresh,
caller-created disposable root. It records an intent first and never clears it.
No production backend selection, Arr/Jellyfin calls, or deletion operations.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_operation_coordinator import SQLiteOperationCoordinator
from app.sqlite_recovery_fingerprint import capture_directory_fingerprint
from app.state_store import GuardedSQLiteStateStore

STAGES = ("transient", "holding", "removal", "keep")


def rehearse_disposable_move(*, root, database, operation_id, media_key,
                            source_stage="transient", destination_stage="holding",
                            after_intent=None, after_rename=None):
    """Run a single disposable rename; failures leave an unresolved intent.

    Hooks are for test fault injection only. This deliberately does not
    reconcile the operation or update lifecycle clocks.
    """
    root = Path(root)
    if (not root.is_absolute() or root.is_symlink()
            or not root.is_dir() or root.resolve() != root):
        raise RuntimeError("Invalid disposable root")
    marker = root / ".sqlite_disposable_rehearsal"
    if (marker.is_symlink() or not marker.is_file()
            or marker.read_text() != "DISPOSABLE ONLY\n"):
        raise RuntimeError("Disposable root marker missing")
    database = Path(database)
    if (not database.is_absolute() or database.is_symlink()
            or database.parent != root or database.name != "state.db"):
        raise RuntimeError("Disposable database must be root/state.db")
    if source_stage not in STAGES or destination_stage not in STAGES:
        raise RuntimeError("Unsupported stage")
    if (source_stage, destination_stage) not in {
        ("transient", "holding"), ("transient", "keep"),
        ("holding", "removal"), ("holding", "keep"), ("removal", "keep"),
    }:
        raise RuntimeError("Unsupported transition")
    if not isinstance(media_key, str) or not media_key:
        raise RuntimeError("Invalid media key")
    paths = {}
    for stage in STAGES:
        stage_root = root / stage
        if stage_root.is_symlink() or not stage_root.is_dir():
            raise RuntimeError("Unsafe disposable stage directory")
        paths[stage] = str(stage_root / "Movie")
    source, destination = paths[source_stage], paths[destination_stage]
    if (capture_directory_fingerprint(source)["status"] != "captured"
            or capture_directory_fingerprint(destination)["status"] != "missing"):
        raise RuntimeError("Disposable source/destination not uniquely ready")
    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    coordinator = SQLiteOperationCoordinator(session)
    coordinator.begin_move_with_evidence(
        operation_id, {"media_key": media_key,
                       "source": source, "destination": destination},
    )
    if after_intent is not None:
        after_intent()
    # The durable intent now exists. Any exception from here on must NOT
    # cause an automatic retry or rollback; recovery must inspect the intent.
    os.rename(source, destination)
    if after_rename is not None:
        after_rename()
    coordinator.mark_applied(operation_id)
    return {"status": "pending_reconciliation",
            "production_activation": "disabled",
            "intent_clearance": "blocked", "replay_allowed": False}
