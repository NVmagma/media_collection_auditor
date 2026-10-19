"""Read-only missing-both recovery classification on disposable SQLite state."""
from pathlib import Path
import sys

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_operation_coordinator import SQLiteOperationCoordinator
from app.sqlite_recovery_offline_evidence import inspect_offline_move_evidence
from app.sqlite_recovery_report import inspect_pending_recovery_status
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore

PREFIX = "sqlite_both_missing"


def run(action: str, lab: Path = Path("/lab")) -> None:
    if action not in ("create", "verify") or not lab.is_dir() or lab.is_symlink():
        raise RuntimeError("Invalid action or isolated lab")
    db = lab / (PREFIX + ".db")
    source = lab / (PREFIX + "_source")
    destination = lab / (PREFIX + "_destination")
    if any(p.is_symlink() for p in (db, source, destination)):
        raise RuntimeError("Symlinked fixture refused")
    if action == "create":
        if any(p.exists() for p in (db, source, destination)):
            raise RuntimeError("Existing fixture refused")
        write_offline_snapshot({section: {} for section in SECTIONS}, db)
        session = RevisionedAuditSession(GuardedSQLiteStateStore(db))
        SQLiteOperationCoordinator(session).begin(
            PREFIX, "move", {"source": str(source), "destination": str(destination)}
        )
        print("Both-missing fixture recorded; use a new container to verify")
        return
    if source.exists() or destination.exists():
        raise RuntimeError("Fixture paths unexpectedly exist")
    state_before = inspect_pending_recovery_status(db)
    first = inspect_offline_move_evidence(db)
    second = inspect_offline_move_evidence(db)
    state_after = inspect_pending_recovery_status(db)
    if (state_before != state_after or first != second
            or state_before.get("status") != "blocked"
            or state_before.get("operation_id") != PREFIX
            or first.get("filesystem_interpretation") != "both_missing"
            or first.get("status") != "blocked"
            or first.get("authorization") != "not_authorized"
            or first.get("reconciliation") != "disabled"
            or first.get("storage_authority") != "json"
            or first.get("production_activation") != "disabled"):
        raise RuntimeError("Both-missing inspection did not fail closed")
    print("Both-missing inspection verified: status=blocked")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m scripts.sqlite_lab_missing_inspection create|verify")
    try:
        run(sys.argv[1])
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"Both-missing inspection blocked: {exc}") from exc
