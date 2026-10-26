"""Read-only SQLite audit preflight tests using disposable artifacts."""

import json

import pytest

from app.sqlite_audit_preflight import prepare_sqlite_audit_state
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS


def _artifacts(tmp_path):
    source = tmp_path / "state.json"
    backup = tmp_path / "state.backup.json"
    database = tmp_path / "state.db"
    state = {section: {} for section in SECTIONS}
    state["first_seen"]["Movie"] = "2024-01-01T01:02:03"
    state["legacy"] = {"original": [1, None]}
    raw = json.dumps(state).encode()
    source.write_bytes(raw)
    backup.write_bytes(raw)
    write_offline_snapshot(state, database)
    return source, backup, database, state


def test_preflight_accepts_identical_artifacts_without_writing(tmp_path):
    source, backup, database, state = _artifacts(tmp_path)
    before = (source.read_bytes(), backup.read_bytes(), database.read_bytes())
    store, loaded, revision = prepare_sqlite_audit_state(source, backup, database)
    assert loaded == state
    assert revision == 0
    assert not hasattr(store, "save")
    assert before == (source.read_bytes(), backup.read_bytes(), database.read_bytes())


def test_preflight_rejects_json_backup_mismatch(tmp_path):
    source, backup, database, _ = _artifacts(tmp_path)
    source.write_text('{"first_seen": {}}')
    with pytest.raises(RuntimeError):
        prepare_sqlite_audit_state(source, backup, database)


def test_preflight_rejects_changed_sqlite_snapshot(tmp_path):
    source, backup, database, _ = _artifacts(tmp_path)
    import sqlite3
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE state_entries SET value_json=? WHERE section='first_seen'",
            ('"2023-01-01T00:00:00"',),
        )
    with pytest.raises(RuntimeError):
        prepare_sqlite_audit_state(source, backup, database)


def test_preflight_rejects_already_written_database(tmp_path):
    source, backup, database, state = _artifacts(tmp_path)
    from app.state_store import GuardedSQLiteStateStore
    store = GuardedSQLiteStateStore(database)
    store.save_if_revision(state, 0)
    with pytest.raises(RuntimeError, match="already modified"):
        prepare_sqlite_audit_state(source, backup, database)


def test_preflight_rejects_missing_database(tmp_path):
    source, backup, database, _ = _artifacts(tmp_path)
    database.unlink()
    with pytest.raises(RuntimeError):
        prepare_sqlite_audit_state(source, backup, database)
