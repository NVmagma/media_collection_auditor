"""Disposable integration checks for the read-only SQLite adapter."""

import json

import pytest

from app.sqlite_isolated_adapter import inspect_isolated_audit_state
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore


def _artifacts(tmp_path):
    source, backup, database = (tmp_path / n for n in (
        "state.json", "backup.json", "state.db"
    ))
    state = {section: {} for section in SECTIONS}
    state["first_seen"]["DISPOSABLE/Example"] = "2024-01-01T00:00:00"
    source.write_text(json.dumps(state))
    backup.write_bytes(source.read_bytes())
    write_offline_snapshot(state, database)
    return source, backup, database, state


def test_isolated_adapter_reads_without_authorizing_or_writing(tmp_path):
    source, backup, database, expected = _artifacts(tmp_path)
    original_bytes = (source.read_bytes(), backup.read_bytes(), database.read_bytes())
    report = inspect_isolated_audit_state(source, backup, database)
    assert report["state"] == expected
    assert report["revision"] == 0
    assert report["authorization"] == "not_authorized"
    assert report["production_activation"] == "disabled"
    assert report["storage_authority"] == "json"
    report["state"]["first_seen"].clear()
    assert GuardedSQLiteStateStore(database).load_with_revision() == (expected, 0)
    assert (source.read_bytes(), backup.read_bytes(), database.read_bytes()) == original_bytes


def test_isolated_adapter_rejects_mismatched_backup(tmp_path):
    source, backup, database, _ = _artifacts(tmp_path)
    backup.write_text("{}")
    before = database.read_bytes()
    with pytest.raises(RuntimeError):
        inspect_isolated_audit_state(source, backup, database)
    assert database.read_bytes() == before


def test_isolated_adapter_rejects_divergent_sqlite_state(tmp_path):
    source, backup, database, _ = _artifacts(tmp_path)
    store = GuardedSQLiteStateStore(database)
    state, revision = store.load_with_revision()
    state["keep_seen"]["DISPOSABLE/Example"] = state["first_seen"].pop("DISPOSABLE/Example")
    store.save_if_revision(state, revision)
    before = store.load_with_revision()
    with pytest.raises(RuntimeError):
        inspect_isolated_audit_state(source, backup, database)
    assert store.load_with_revision() == before
