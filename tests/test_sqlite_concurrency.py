"""Optimistic concurrency tests for the isolated SQLite backend."""

import pytest

from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.sqlite_store import SQLiteStateStore


def _empty():
    return {section: {} for section in SECTIONS}


def test_stale_writer_cannot_erase_newer_tracking(tmp_path):
    database = tmp_path / "tracking.db"
    write_offline_snapshot(_empty(), database)
    first = SQLiteStateStore(database)
    second = SQLiteStateStore(database)
    first_state, first_revision = first.load_with_revision()
    second_state, second_revision = second.load_with_revision()
    assert first_revision == second_revision == 0
    first_state["first_seen"]["Movie"] = "2024-01-01T01:02:03"
    first.save_if_revision(first_state, first_revision)
    second_state["keep_seen"]["Show"] = "2024-01-02T01:02:03"
    with pytest.raises(RuntimeError, match="Stale SQLite state revision"):
        second.save_if_revision(second_state, second_revision)
    assert second.load() == first_state
    updated, revision = second.load_with_revision()
    assert revision == 1
    updated["keep_seen"]["Show"] = "2024-01-02T01:02:03"
    second.save_if_revision(updated, revision)
    assert second.load_with_revision() == (updated, 2)


def test_invalid_revision_rejected_without_modification(tmp_path):
    database = tmp_path / "tracking.db"
    write_offline_snapshot(_empty(), database)
    store = SQLiteStateStore(database)
    for revision in (-1, True, "0"):
        with pytest.raises(RuntimeError, match="Invalid expected"):
            store.save_if_revision(_empty(), revision)
    assert store.load_with_revision() == (_empty(), 0)


def test_corrupt_revision_blocks_guarded_save(tmp_path):
    import sqlite3

    database = tmp_path / "tracking.db"
    write_offline_snapshot(_empty(), database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO metadata (key, value) VALUES ('state_revision', 'broken')"
        )
    store = SQLiteStateStore(database)
    with pytest.raises(RuntimeError, match="revision"):
        store.load_with_revision()
    with pytest.raises(RuntimeError, match="revision"):
        store.save_if_revision(_empty(), 0)
