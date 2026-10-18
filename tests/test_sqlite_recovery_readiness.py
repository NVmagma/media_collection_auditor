"""Recovery readiness must remain advisory and non-mutating."""

import json

import pytest

from app.sqlite_audit_bootstrap import open_isolated_sqlite_audit
from app.sqlite_migration import create_offline_migration_snapshot
from app.sqlite_operation_coordinator import SQLiteOperationCoordinator
from app.sqlite_recovery_readiness import inspect_recovery_readiness, recovery_readiness_from_report
from app.state_store import GuardedSQLiteStateStore


def test_readiness_blocks_pending_operation_without_mutation(tmp_path):
    source = tmp_path / "source.json"
    backup = tmp_path / "backup.json"
    database = tmp_path / "audit.db"
    source.write_text(json.dumps({"original": True}))
    create_offline_migration_snapshot(source, backup, database)
    session = open_isolated_sqlite_audit(source, backup, database)
    src = tmp_path / "Waiting" / "Movie"
    dst = tmp_path / "Keep" / "Movie"
    src.mkdir(parents=True)
    dst.parent.mkdir()
    SQLiteOperationCoordinator(session).begin("op-1", "move", {
        "jellyfin_item_id": "movie-1", "jellyfin_type": "Movie",
        "source": str(src), "destination": str(dst),
    })
    before = GuardedSQLiteStateStore(database).load_with_revision()
    result = inspect_recovery_readiness(database)
    checks = {item["id"]: item["status"] for item in result["checks"]}
    assert checks["pending_intent"] == "blocked"
    assert checks["external_verification"] == "not_performed"
    assert checks["automatic_reconciliation"] == "disabled"
    assert checks["production_cutover"] == "not_approved"
    assert result["recovery_clearance"] == "not_authorized"
    assert "Waiting" not in str(result)
    assert "Keep" not in str(result)
    assert "movie-1" not in str(result)
    assert GuardedSQLiteStateStore(database).load_with_revision() == before
    assert source.read_bytes() == backup.read_bytes()


def test_missing_database_fails_closed(tmp_path):
    database = tmp_path / "missing.db"
    with pytest.raises(Exception):
        inspect_recovery_readiness(database)
    assert not database.exists()


def test_no_pending_operation_still_does_not_authorize_cutover(tmp_path):
    source = tmp_path / "source.json"
    backup = tmp_path / "backup.json"
    database = tmp_path / "audit.db"
    source.write_text("{}")
    create_offline_migration_snapshot(source, backup, database)
    result = inspect_recovery_readiness(database)
    assert result["status"] == "no_pending_operation"
    assert result["recovery_clearance"] == "not_authorized"
    assert next(c for c in result["checks"] if c["id"] == "pending_intent")["status"] == "clear"


def test_checklist_uses_supplied_snapshot_not_new_database_read(tmp_path):
    report = {
        "status": "blocked", "revision": 7,
        "operation_id": "safe-id", "blocker": "independent_verification_required",
    }
    result = recovery_readiness_from_report(report)
    assert result["status"] == "blocked"
    assert result["recovery_clearance"] == "not_authorized"
    assert next(c for c in result["checks"] if c["id"] == "pending_intent")["status"] == "blocked"
    assert "safe-id" not in str(result)


def test_checklist_and_status_stay_consistent_across_distinct_snapshots():
    before = recovery_readiness_from_report({"status": "blocked", "revision": 1})
    after = recovery_readiness_from_report({"status": "no_pending_operation", "revision": 2})
    assert before["status"] == "blocked"
    assert after["status"] == "no_pending_operation"
    assert before["checks"][1]["status"] == "blocked"
    assert after["checks"][1]["status"] == "clear"
