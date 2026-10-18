"""Regression tests for offline SQLite snapshot creation."""

import sqlite3

import pytest

from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import read_snapshot


def test_snapshot_round_trip_preserves_clocks_and_pending_retry(tmp_path):
    destination = tmp_path / "snapshot.db"
    state = {
        "first_seen": {"Movie": "2025-01-02T03:04:05"},
        "queued": {},
        "in_removal": {},
        "keep_seen": {"Series/Show": "2025-02-03T04:05:06"},
        "arr_sync_pending": {
            "Movie": {"stage": "keep", "root": "/media/Movies_keep", "monitored": False}
        },
    }
    write_offline_snapshot(state, destination)
    assert read_snapshot(destination) == state


def test_existing_database_is_never_replaced(tmp_path):
    destination = tmp_path / "snapshot.db"
    destination.write_bytes(b"existing data")
    with pytest.raises(RuntimeError, match="already exists"):
        write_offline_snapshot({section: {} for section in (
            "first_seen", "queued", "in_removal", "keep_seen", "arr_sync_pending"
        )}, destination)
    assert destination.read_bytes() == b"existing data"


def test_invalid_state_does_not_create_database(tmp_path):
    destination = tmp_path / "snapshot.db"
    state = {section: {} for section in (
        "first_seen", "queued", "in_removal", "keep_seen", "arr_sync_pending"
    )}
    state["queued"]["Movie"] = "2999-01-01T00:00:00"
    with pytest.raises(RuntimeError, match="timestamp"):
        write_offline_snapshot(state, destination)
    assert not destination.exists()


def test_database_has_expected_schema_version(tmp_path):
    destination = tmp_path / "snapshot.db"
    state = {section: {} for section in (
        "first_seen", "queued", "in_removal", "keep_seen", "arr_sync_pending"
    )}
    write_offline_snapshot(state, destination)
    with sqlite3.connect(f"file:{destination}?mode=ro", uri=True) as connection:
        assert connection.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone() == ("1",)
