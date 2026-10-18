"""Transactional SQLite store tests; never touch production state."""

import sqlite3

import pytest

from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.sqlite_store import SQLiteStateStore


def _state():
    return {**{section: {} for section in SECTIONS},
            "legacy": {"nested": [True, None]}}


def test_save_round_trip_and_reopen(tmp_path):
    path = tmp_path / "state.db"
    original = _state()
    write_offline_snapshot(original, path)
    store = SQLiteStateStore(path)
    updated = _state()
    updated["first_seen"]["Movie"] = "2024-01-01T01:02:03"
    updated["arr_sync_pending"]["Movie"] = {
        "stage": "keep", "root": "/media/Movies_keep", "monitored": False,
    }
    store.save(updated)
    assert SQLiteStateStore(path).load() == updated


def test_missing_database_is_not_created(tmp_path):
    path = tmp_path / "missing.db"
    with pytest.raises(RuntimeError, match="unavailable"):
        SQLiteStateStore(path).save(_state())
    assert not path.exists()


def test_invalid_state_does_not_modify_database(tmp_path):
    path = tmp_path / "state.db"
    write_offline_snapshot(_state(), path)
    bad = _state()
    bad["queued"]["Movie"] = "2999-01-01T00:00:00"
    with pytest.raises(RuntimeError, match="timestamp"):
        SQLiteStateStore(path).save(bad)
    assert SQLiteStateStore(path).load() == _state()


def test_transaction_failure_rolls_back_all_rows(tmp_path, monkeypatch):
    path = tmp_path / "state.db"
    original = _state()
    write_offline_snapshot(original, path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TRIGGER reject_update BEFORE INSERT ON state_entries "
            "BEGIN SELECT RAISE(ABORT, 'simulated write failure'); END"
        )
    changed = _state()
    changed["first_seen"]["Movie"] = "2024-01-01T01:02:03"
    with pytest.raises(RuntimeError, match="write failed"):
        SQLiteStateStore(path).save(changed)
    assert SQLiteStateStore(path).load() == original


def test_incomplete_database_never_accepted(tmp_path):
    path = tmp_path / "state.db"
    write_offline_snapshot(_state(), path)
    with sqlite3.connect(path) as connection:
        connection.execute("DELETE FROM metadata WHERE key='snapshot_complete'")
    with pytest.raises(RuntimeError, match="incomplete"):
        SQLiteStateStore(path).save(_state())
