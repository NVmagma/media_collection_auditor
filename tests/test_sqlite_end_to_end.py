"""End-to-end offline conversion safety using disposable tracking state."""

import json

import pytest

from app.sqlite_lock import audit_run_lock, state_writer_lock
from app.sqlite_migration import create_offline_migration_snapshot
from app.sqlite_recovery import inspect_migration_artifacts
from app.sqlite_state import SECTIONS, read_snapshot


def _paths(tmp_path):
    return (tmp_path / "state.json", tmp_path / "state.backup.json",
            tmp_path / "state.sqlite")


def _state():
    state = {section: {} for section in SECTIONS}
    state["first_seen"]["Movies/Example (2020)"] = "2024-01-01T12:34:56"
    state["queued"]["Shows/Example/Season 01"] = "2024-02-03T04:05:06"
    state["keep_seen"]["Movies/Protected (2021)"] = "2024-03-04T05:06:07"
    state["arr_sync_pending"]["Movies/Example (2020)"] = {
        "stage": "keep", "root": "/media/Movies_keep", "monitored": False
    }
    return state


def test_active_audit_blocks_conversion_before_artifacts(tmp_path):
    source, backup, database = _paths(tmp_path)
    original = json.dumps(_state(), indent=2).encode()
    source.write_bytes(original)
    with audit_run_lock(source):
        with pytest.raises(RuntimeError, match="Another offline migration"):
            create_offline_migration_snapshot(source, backup, database)
        assert source.read_bytes() == original
        assert not backup.exists()
        assert not database.exists()
    assert inspect_migration_artifacts(source, backup, database) == {
        "source": "valid", "backup": "missing", "database": "missing",
        "source_backup": "unverified",
    }


def test_conversion_after_audit_preserves_every_known_section(tmp_path):
    source, backup, database = _paths(tmp_path)
    state = _state()
    source.write_text(json.dumps(state, indent=2), encoding="utf-8")
    with audit_run_lock(source):
        with state_writer_lock(source):
            state["in_removal"]["Movies/Old (1999)"] = "2024-04-05T06:07:08"
            source.write_text(json.dumps(state, indent=2), encoding="utf-8")
    original = source.read_bytes()
    create_offline_migration_snapshot(source, backup, database)
    assert source.read_bytes() == original
    assert backup.read_bytes() == original
    assert read_snapshot(database) == state
    assert inspect_migration_artifacts(source, backup, database) == {
        "source": "valid", "backup": "valid", "database": "complete",
        "source_backup": "identical",
    }


def test_existing_backup_refuses_retry_without_overwriting(tmp_path):
    source, backup, database = _paths(tmp_path)
    source.write_text(json.dumps(_state()), encoding="utf-8")
    backup.write_bytes(b"historical backup must remain intact")
    with pytest.raises(RuntimeError, match="Backup already exists"):
        create_offline_migration_snapshot(source, backup, database)
    assert backup.read_bytes() == b"historical backup must remain intact"
    assert not database.exists()


def test_unknown_history_round_trips_without_discarding(tmp_path):
    source, backup, database = _paths(tmp_path)
    state = _state()
    state["future_tracking_field"] = {
        "preserve": ["this", {"nested": True, "value": None}],
        "counter": 0,
    }
    state["legacy_flags"] = ["keep", "protected"]
    source.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    original = source.read_bytes()
    create_offline_migration_snapshot(source, backup, database)
    assert source.read_bytes() == original
    assert backup.read_bytes() == original
    assert read_snapshot(database) == state
    assert inspect_migration_artifacts(source, backup, database)["database"] == "complete"
