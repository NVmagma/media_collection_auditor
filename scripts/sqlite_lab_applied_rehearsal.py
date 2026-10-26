"""Offline crash-window rehearsal: applied intent must never auto-reconcile.

This deliberately simulates an 'applied' checkpoint without moving anything.
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
DB_NAME = "sqlite_applied_rehearsal.db"
OP_ID = "isolated-applied-checkpoint-1"


def run(action: str, lab: Path = LAB) -> None:
    if not lab.is_dir() or lab.is_symlink():
        raise RuntimeError("Dedicated lab mount unavailable")
    db = lab / DB_NAME
    if db.is_symlink():
        raise RuntimeError("Symlinked database refused")
    if action == "create":
        if db.exists():
            raise RuntimeError("Existing database refused")
        write_offline_snapshot({section: {} for section in SECTIONS}, db)
        session = RevisionedAuditSession(GuardedSQLiteStateStore(db))
        coordinator = SQLiteOperationCoordinator(session)
        coordinator.begin(OP_ID, "arr_sync", {"fixture": "no-external-action"})
        coordinator.mark_applied(OP_ID)
        report = inspect_pending_recovery_status(db)
        if (report.get("status") != "blocked"
                or report.get("operation_phase") != "applied_pending_reconciliation"):
            raise RuntimeError("Applied checkpoint not safely persisted")
        print("Applied checkpoint persisted; no external action executed")
    elif action == "verify":
        before = inspect_pending_recovery_status(db)
        if (before.get("status") != "blocked"
                or before.get("operation_id") != OP_ID
                or before.get("operation_kind") != "arr_sync"
                or before.get("operation_phase") != "applied_pending_reconciliation"
                or before.get("storage_authority") != "json"):
            raise RuntimeError("Applied intent unavailable or unsafe")
        session = RevisionedAuditSession(GuardedSQLiteStateStore(db))
        coordinator = SQLiteOperationCoordinator(session)
        try:
            coordinator.reconcile(OP_ID, session.state)
        except RuntimeError as exc:
            if "blocked pending trusted verification" not in str(exc):
                raise
        else:
            raise RuntimeError("Reconciliation unexpectedly authorized")
        try:
            coordinator.begin("new-intent", "arr_sync", {"fixture": "no-action"})
        except RuntimeError as exc:
            if "Unresolved SQLite operation" not in str(exc):
                raise
        else:
            raise RuntimeError("New operation unexpectedly authorized")
        after = inspect_pending_recovery_status(db)
        if before != after or session.state[INTENTS_KEY]["phase"] != "applied_pending_reconciliation":
            raise RuntimeError("Verification changed pending operation")
        print(f"Applied restart verified: revision={before['revision']}, status=blocked")
    else:
        raise RuntimeError("Expected create or verify")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m scripts.sqlite_lab_applied_rehearsal create|verify")
    try:
        run(sys.argv[1])
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"SQLite applied rehearsal blocked: {exc}") from exc
