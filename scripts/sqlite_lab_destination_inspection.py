"""Offline destination-only recovery inspection with disposable fixtures."""
from pathlib import Path
import sys
from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_operation_coordinator import SQLiteOperationCoordinator
from app.sqlite_recovery_offline_evidence import inspect_offline_move_evidence
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore

PREFIX = "sqlite_destination_only"


def run(action: str, lab: Path = Path("/lab")) -> None:
    if action not in {"create", "verify"} or not lab.is_dir() or lab.is_symlink():
        raise RuntimeError("Invalid action or isolated lab")
    db = lab / (PREFIX + ".db")
    source = lab / (PREFIX + "_source")
    dest = lab / (PREFIX + "_destination")
    if any(p.is_symlink() for p in (db, source, dest)):
        raise RuntimeError("Symlinked fixture refused")
    if action == "create":
        if any(p.exists() for p in (db, source, dest)):
            raise RuntimeError("Existing fixture refused")
        # No source exists: model the post-interruption observation directly.
        dest.mkdir()
        write_offline_snapshot({section: {} for section in SECTIONS}, db)
        session = RevisionedAuditSession(GuardedSQLiteStateStore(db))
        SQLiteOperationCoordinator(session).begin(
            PREFIX, "move", {"source": str(source), "destination": str(dest)}
        )
        print("Destination-only fixture recorded; use new container for verify")
        return
    if source.exists() or not dest.is_dir():
        raise RuntimeError("Fixture state unexpected")
    before = inspect_offline_move_evidence(db)
    if (before.get("status") != "blocked"
            or before.get("authorization") != "not_authorized"
            or before.get("reconciliation") != "disabled"
            or before.get("filesystem_interpretation") != "destination_only_unverified"
            or before.get("storage_authority") != "json"
            or before.get("production_activation") != "disabled"):
        raise RuntimeError("Unsafe destination-only recovery result")
    after = inspect_offline_move_evidence(db)
    if before != after:
        raise RuntimeError("Recovery inspection changed")
    print("Destination-only inspection verified: status=blocked")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m scripts.sqlite_lab_destination_inspection create|verify")
    try:
        run(sys.argv[1])
    except (RuntimeError, OSError, ValueError) as exc:
        raise SystemExit(f"Destination inspection blocked: {exc}") from exc
