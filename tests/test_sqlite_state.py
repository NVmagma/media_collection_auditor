"""Safety tests for the inspection-only SQLite prototype."""

import json
import sqlite3

import pytest

from app.sqlite_state import SCHEMA_SQL, read_snapshot


def test_missing_snapshot_does_not_create_file(tmp_path):
    path = tmp_path / "missing.db"
    with pytest.raises(RuntimeError, match="unavailable"):
        read_snapshot(path)
    assert not path.exists()


def test_valid_snapshot_preserves_values(tmp_path):
    path = tmp_path / "state.db"
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA_SQL)
        db.execute("INSERT INTO metadata VALUES (?, ?)", ("schema_version", "1"))
        db.execute(
            "INSERT INTO state_entries VALUES (?, ?, ?)",
            ("queued", "Movies:Example", json.dumps("2025-01-02T03:04:05")),
        )
        pending = {"stage": "keep", "root": "/media/Movies_keep", "monitored": True}
        db.execute(
            "INSERT INTO state_entries VALUES (?, ?, ?)",
            ("arr_sync_pending", "Movies:Example", json.dumps(pending)),
        )
    state = read_snapshot(path)
    assert state["queued"]["Movies:Example"] == "2025-01-02T03:04:05"
    assert state["arr_sync_pending"]["Movies:Example"] == pending
    assert state["first_seen"] == {}


def test_unknown_schema_fails_closed(tmp_path):
    path = tmp_path / "state.db"
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA_SQL)
        db.execute("INSERT INTO metadata VALUES (?, ?)", ("schema_version", "999"))
    with pytest.raises(RuntimeError, match="schema version"):
        read_snapshot(path)


def test_corrupt_database_fails_closed(tmp_path):
    path = tmp_path / "state.db"
    path.write_bytes(b"not a database")
    with pytest.raises(RuntimeError, match="unreadable"):
        read_snapshot(path)


def test_invalid_row_fails_closed(tmp_path):
    path = tmp_path / "state.db"
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA_SQL)
        db.execute("INSERT INTO metadata VALUES (?, ?)", ("schema_version", "1"))
        db.execute(
            "INSERT INTO state_entries VALUES (?, ?, ?)",
            ("first_seen", "Movies:Example", json.dumps({"not": "a timestamp"})),
        )
    with pytest.raises(RuntimeError, match="invalid lifecycle timestamp"):
        read_snapshot(path)
