"""Failure-injection tests for interrupted offline migration on disposable files."""

import json
import sqlite3

import pytest

from app.sqlite_integrity import verify_migration_integrity
from app.sqlite_migration import create_offline_migration_snapshot
from app.sqlite_recovery import inspect_migration_artifacts
from app.sqlite_state import SCHEMA_SQL, SCHEMA_VERSION


def _paths(tmp_path):
    return tmp_path / "state.json", tmp_path / "backup.json", tmp_path / "state.db"


def _source(source):
    original = json.dumps({
        "first_seen": {"Movie": "2024-01-01T01:02:03"},
        "legacy": {"nested": ["preserve", True]},
    }).encode()
    source.write_bytes(original)
    return original


def test_interruption_after_backup_never_retries_or_overwrites(tmp_path, monkeypatch):
    source, backup, database = _paths(tmp_path)
    original = _source(source)

    def interrupted_writer(state, destination):
        raise OSError("simulated power loss before SQLite creation")

    monkeypatch.setattr("app.sqlite_migration.write_offline_snapshot", interrupted_writer)
    with pytest.raises(OSError, match="simulated power loss"):
        create_offline_migration_snapshot(source, backup, database)
    assert source.read_bytes() == backup.read_bytes() == original
    assert not database.exists()
    assert inspect_migration_artifacts(source, backup, database)["database"] == "missing"
    with pytest.raises(RuntimeError, match="Backup already exists"):
        create_offline_migration_snapshot(source, backup, database)
    assert backup.read_bytes() == original


def test_incomplete_transaction_remains_untrusted_and_preserved(tmp_path):
    source, backup, database = _paths(tmp_path)
    original = _source(source)
    backup.write_bytes(original)
    with sqlite3.connect(database) as db:
        db.executescript(SCHEMA_SQL)
        db.execute("INSERT INTO metadata VALUES (?, ?)", ("schema_version", str(SCHEMA_VERSION)))
        db.execute("INSERT INTO state_entries VALUES (?, ?, ?)",
                   ("first_seen", "Movie", json.dumps("2024-01-01T01:02:03")))
    before = [path.read_bytes() for path in (source, backup, database)]
    assert inspect_migration_artifacts(source, backup, database)["database"] == "incomplete_or_invalid"
    with pytest.raises(RuntimeError, match="incomplete"):
        verify_migration_integrity(source, backup, database)
    with pytest.raises(RuntimeError, match="already exists"):
        create_offline_migration_snapshot(source, backup, database)
    assert [path.read_bytes() for path in (source, backup, database)] == before


def test_sqlite_write_failure_keeps_original_and_partial_artifact(tmp_path, monkeypatch):
    source, backup, database = _paths(tmp_path)
    original = _source(source)

    def partial_writer(state, destination):
        destination.write_bytes(b"partial SQLite after disk failure")
        raise OSError("simulated disk full")

    monkeypatch.setattr("app.sqlite_migration.write_offline_snapshot", partial_writer)
    with pytest.raises(OSError, match="simulated disk full"):
        create_offline_migration_snapshot(source, backup, database)
    assert source.read_bytes() == backup.read_bytes() == original
    assert database.read_bytes() == b"partial SQLite after disk failure"
    assert inspect_migration_artifacts(source, backup, database)["database"] == "incomplete_or_invalid"
    with pytest.raises(RuntimeError, match="already exists"):
        create_offline_migration_snapshot(source, backup, database)


def test_completed_but_tampered_snapshot_is_not_verified(tmp_path):
    source, backup, database = _paths(tmp_path)
    _source(source)
    create_offline_migration_snapshot(source, backup, database)
    with sqlite3.connect(database) as db:
        db.execute("DELETE FROM state_entries WHERE section = 'first_seen'")
    assert inspect_migration_artifacts(source, backup, database)["database"] == "complete"
    with pytest.raises(RuntimeError, match="differs"):
        verify_migration_integrity(source, backup, database)
