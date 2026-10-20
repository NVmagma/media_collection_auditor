"""Production integration preflight must remain non-authorizing."""

import json

import pytest

from app.sqlite_production_preflight import inspect_production_integration
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS


def _artifacts(tmp_path):
    source = tmp_path / "source.json"
    backup = tmp_path / "backup.json"
    database = tmp_path / "state.db"
    state = {section: {} for section in SECTIONS}
    state["first_seen"]["DISPOSABLE/Movie"] = "2024-01-01T00:00:00"
    source.write_text(json.dumps(state))
    backup.write_bytes(source.read_bytes())
    write_offline_snapshot(state, database)
    return source, backup, database


def test_valid_migration_is_not_production_authorization(tmp_path):
    paths = _artifacts(tmp_path)
    before = [path.read_bytes() for path in paths]
    result = inspect_production_integration("json", *paths)
    assert result["ready_for_isolated_review"] is True
    assert result["ready_for_production"] is False
    assert result["authorization"] == "not_authorized"
    assert result["storage_authority"] == "json"
    assert result["production_activation"] == "disabled"
    assert "trusted_move_recovery_not_implemented" in result["blockers"]
    assert [path.read_bytes() for path in paths] == before


@pytest.mark.parametrize("backend", ["sqlite", "", "SQLite", None])
def test_unsupported_backend_is_reported(tmp_path, backend):
    result = inspect_production_integration(backend, *_artifacts(tmp_path))
    assert "unsupported_production_backend" in result["blockers"]
    assert result["ready_for_production"] is False


def test_missing_artifacts_fail_closed(tmp_path):
    paths = tuple(tmp_path / name for name in ("missing.json", "backup.json", "state.db"))
    result = inspect_production_integration("json", *paths)
    assert "migration_artifact_missing" in result["blockers"]
    assert result["ready_for_isolated_review"] is False


def test_backup_mismatch_is_reported_without_writes(tmp_path):
    paths = _artifacts(tmp_path)
    paths[1].write_text("{}")
    before = [path.read_bytes() for path in paths]
    result = inspect_production_integration("json", *paths)
    assert "json_backup_mismatch" in result["blockers"]
    assert [path.read_bytes() for path in paths] == before


def test_sqlite_snapshot_mismatch_is_reported(tmp_path):
    paths = _artifacts(tmp_path)
    paths[0].write_text("{}")
    paths[1].write_bytes(paths[0].read_bytes())
    result = inspect_production_integration("json", *paths)
    assert "sqlite_snapshot_mismatch" in result["blockers"]
    assert result["ready_for_production"] is False


def test_unresolved_intent_blocks_review(tmp_path):
    state = {section: {} for section in SECTIONS}
    state["sqlite_pending_operations"] = {
        "id": "pending", "kind": "move", "phase": "intent_recorded",
        "details": {"source": "/disposable/source"},
    }
    source, backup, database = (tmp_path / name for name in ("a.json", "b.json", "c.db"))
    source.write_text(json.dumps(state))
    backup.write_bytes(source.read_bytes())
    write_offline_snapshot(state, database)
    result = inspect_production_integration("json", source, backup, database)
    assert "unresolved_operation_requires_reconciliation" in result["blockers"]
    assert result["ready_for_production"] is False
