"""Disposable-data tests for read-only migration integrity verification."""

import json
import sqlite3

import pytest

from app.sqlite_integrity import verify_migration_integrity
from app.sqlite_migration import create_offline_migration_snapshot


def _converted(tmp_path):
    source = tmp_path / "state.json"
    backup = tmp_path / "backup.json"
    database = tmp_path / "state.db"
    state = {
        "first_seen": {"Movies/Example": "2024-01-02T03:04:05"},
        "queued": {}, "in_removal": {}, "keep_seen": {},
        "arr_sync_pending": {
            "Movies/Example": {
                "stage": "keep", "root": "/media/Movies_keep",
                "monitored": False, "attempts": 2,
            }
        },
        "legacy": {"nested": [None, True, {"title": "café"}]},
    }
    source.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    create_offline_migration_snapshot(source, backup, database)
    return source, backup, database


def test_valid_snapshot_matches_backup_and_source(tmp_path):
    paths = _converted(tmp_path)
    before = [path.read_bytes() for path in paths]
    verify_migration_integrity(*paths)
    assert [path.read_bytes() for path in paths] == before


@pytest.mark.parametrize("change", ["timestamp", "arr_retry", "unknown_field"])
def test_semantic_tampering_is_rejected(tmp_path, change):
    source, backup, database = _converted(tmp_path)
    with sqlite3.connect(database) as db:
        if change == "timestamp":
            db.execute(
                "UPDATE state_entries SET value_json = ? WHERE section = 'first_seen'",
                (json.dumps("2024-01-03T03:04:05"),),
            )
        elif change == "arr_retry":
            db.execute(
                "UPDATE state_entries SET value_json = ? WHERE section = 'arr_sync_pending'",
                (json.dumps({"stage": "holding", "root": "/media/Movies_keep",
                             "monitored": False, "attempts": 2}),),
            )
        else:
            db.execute(
                "UPDATE extra_state SET value_json = ? WHERE key = 'legacy'",
                (json.dumps({"nested": [None, False]}),),
            )
    with pytest.raises(RuntimeError, match="differs"):
        verify_migration_integrity(source, backup, database)


def test_source_changed_after_backup_is_rejected(tmp_path):
    source, backup, database = _converted(tmp_path)
    source.write_bytes(source.read_bytes() + b" ")
    with pytest.raises(RuntimeError, match="Source JSON differs"):
        verify_migration_integrity(source, backup, database)


def test_invalid_database_is_rejected_without_modification(tmp_path):
    source, backup, database = _converted(tmp_path)
    database.write_bytes(b"corrupt sqlite")
    original = database.read_bytes()
    with pytest.raises(RuntimeError):
        verify_migration_integrity(source, backup, database)
    assert database.read_bytes() == original


def test_missing_artifact_is_rejected(tmp_path):
    source, backup, database = _converted(tmp_path)
    backup.unlink()
    with pytest.raises(RuntimeError, match="requires all three"):
        verify_migration_integrity(source, backup, database)


def test_duplicate_json_keys_are_rejected(tmp_path):
    source, backup, database = _converted(tmp_path)
    duplicate = b'{"queued":{},"queued":{}}'
    source.write_bytes(duplicate)
    backup.write_bytes(duplicate)
    with pytest.raises(ValueError, match="Duplicate JSON key"):
        verify_migration_integrity(source, backup, database)
