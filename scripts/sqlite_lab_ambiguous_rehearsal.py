"""Rehearse ambiguous filesystem observations with isolated SQLite fixtures.

Never moves media, clears intents, or authorizes recovery.
"""
from __future__ import annotations

from pathlib import Path
import sys

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_operation_coordinator import SQLiteOperationCoordinator
from app.sqlite_recovery_offline_evidence import inspect_offline_move_evidence
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore

LAB = Path("/lab")
SCENARIOS = {"source_only": "source_only", "both_present": "both_present_ambiguous"}


def run(action: str, scenario: str, lab: Path = LAB) -> None:
    if scenario not in SCENARIOS or action not in ("create", "verify"):
        raise RuntimeError("Expected create|verify and source_only|both_present")
    if not lab.is_dir() or lab.is_symlink():
        raise RuntimeError("Dedicated lab mount unavailable")
    prefix = "sqlite_ambiguous_" + scenario
    db = lab / (prefix + ".db")
    source = lab / (prefix + "_source")
    destination = lab / (prefix + "_destination")
    if any(path.is_symlink() for path in (db, source, destination)):
        raise RuntimeError("Symlinked fixture refused")
    if action == "create":
        if any(path.exists() for path in (db, source, destination)):
            raise RuntimeError("Existing fixture refused")
        source.mkdir()
        if scenario == "both_present":
            destination.mkdir()
        write_offline_snapshot({section: {} for section in SECTIONS}, db)
        session = RevisionedAuditSession(GuardedSQLiteStateStore(db))
        SQLiteOperationCoordinator(session).begin_move_with_evidence(
            prefix, {"source": str(source), "destination": str(destination)}
        )
        print("Ambiguous recovery fixture recorded; recreate container before verify")
        return
    if not source.is_dir() or destination.exists() != (scenario == "both_present"):
        raise RuntimeError("Fixture filesystem changed")
    before = inspect_offline_move_evidence(db)
    if (before.get("status") != "blocked"
            or before.get("authorization") != "not_authorized"
            or before.get("reconciliation") != "disabled"
            or before.get("filesystem_interpretation") != SCENARIOS[scenario]
            or before.get("storage_authority") != "json"
            or before.get("production_activation") != "disabled"):
        raise RuntimeError("Recovery inspection failed closed")
    after = inspect_offline_move_evidence(db)
    if before != after:
        raise RuntimeError("Recovery observation changed")
    print(f"Ambiguous recovery verified: {scenario}, status=blocked")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python -m scripts.sqlite_lab_ambiguous_rehearsal create|verify source_only|both_present")
    try:
        run(sys.argv[1], sys.argv[2])
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"SQLite ambiguous rehearsal blocked: {exc}") from exc
