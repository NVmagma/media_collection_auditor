"""Two-container, offline SQLite intent persistence rehearsal.

Only dedicated /lab fixture names are used; never executes media operations.
"""
from __future__ import annotations

from pathlib import Path
import sys

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_operation_coordinator import INTENTS_KEY, SQLiteOperationCoordinator
from app.sqlite_recovery_report import inspect_pending_recovery_status
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore

LAB = Path("/lab")
DATABASE_NAME = "sqlite_intent_rehearsal.db"
SOURCE_NAME = "sqlite_intent_rehearsal_source"
DEST_NAME = "sqlite_intent_rehearsal_destination"
OPERATION_ID = "isolated-unraid-restart-1"


def run(action: str, lab: Path = LAB) -> None:
    if not lab.is_dir() or lab.is_symlink():
        raise RuntimeError("Dedicated lab mount unavailable")
    db = lab / DATABASE_NAME
    source = lab / SOURCE_NAME
    destination = lab / DEST_NAME
    if any(p.is_symlink() for p in (db, source, destination)):
        raise RuntimeError("Symlinked fixture refused")
    if action == "create":
        if any(p.exists() for p in (db, source, destination)):
            raise RuntimeError("Rehearsal fixtures already exist; refusing overwrite")
        source.mkdir()
        write_offline_snapshot({section: {} for section in SECTIONS}, db)
        session = RevisionedAuditSession(GuardedSQLiteStateStore(db))
        SQLiteOperationCoordinator(session).begin_move_with_evidence(
            OPERATION_ID, {"source": str(source), "destination": str(destination)}
        )
        result = inspect_pending_recovery_status(db)
        if result["status"] != "blocked" or result["operation_phase"] != "intent_recorded":
            raise RuntimeError("Intent was not durably blocked")
        print("SQLite intent recorded; stop this container before verify")
    elif action == "verify":
        if not source.is_dir() or destination.exists():
            raise RuntimeError("Disposable filesystem changed across restart")
        before = inspect_pending_recovery_status(db)
        if (before.get("status") != "blocked"
                or before.get("operation_id") != OPERATION_ID
                or before.get("operation_kind") != "move"
                or before.get("operation_phase") != "intent_recorded"
                or before.get("storage_authority") != "json"):
            raise RuntimeError("Persisted SQLite recovery intent missing or unsafe")
        session = RevisionedAuditSession(GuardedSQLiteStateStore(db))
        try:
            SQLiteOperationCoordinator(session).begin(
                "another-intent", "move", {"source": str(source)}
            )
        except RuntimeError as exc:
            if "Unresolved SQLite operation" not in str(exc):
                raise
        else:
            raise RuntimeError("Second operation unexpectedly authorized")
        after = inspect_pending_recovery_status(db)
        if after != before or destination.exists():
            raise RuntimeError("Verification mutated persisted state or media")
        print(f"SQLite restart verified: revision={before['revision']}, status=blocked")
    else:
        raise RuntimeError("Expected create or verify")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m scripts.sqlite_lab_intent_rehearsal create|verify")
    try:
        run(sys.argv[1])
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"SQLite lab rehearsal blocked: {exc}") from exc
