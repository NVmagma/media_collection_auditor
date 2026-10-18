"""Cross-artifact recovery status tests using disposable state."""

import json
import sqlite3

from app.sqlite_migration import create_offline_migration_snapshot
from app.sqlite_recovery import inspect_migration_integrity_status


def _paths(tmp_path):
    return tmp_path / "state.json", tmp_path / "backup.json", tmp_path / "snapshot.db"


def test_complete_and_matching_snapshot_is_verified(tmp_path):
    source, backup, db = _paths(tmp_path)
    source.write_text(json.dumps({
        "first_seen": {"Movie": "2024-01-01T01:02:03"},
        "legacy": {"nested": [True, None]},
    }))
    create_offline_migration_snapshot(source, backup, db)
    before = [p.read_bytes() for p in (source, backup, db)]
    result = inspect_migration_integrity_status(source, backup, db)
    assert result["database"] == "complete"
    assert result["integrity"] == "verified"
    assert [p.read_bytes() for p in (source, backup, db)] == before


def test_structurally_complete_but_missing_tracking_is_mismatch(tmp_path):
    source, backup, db = _paths(tmp_path)
    source.write_text('{"first_seen":{"Movie":"2024-01-01T01:02:03"}}')
    create_offline_migration_snapshot(source, backup, db)
    with sqlite3.connect(db) as connection:
        connection.execute("DELETE FROM state_entries")
    result = inspect_migration_integrity_status(source, backup, db)
    assert result["database"] == "complete"
    assert result["integrity"] == "mismatch_or_unreadable"


def test_incomplete_database_is_not_treated_as_verified(tmp_path):
    source, backup, db = _paths(tmp_path)
    source.write_text("{}")
    backup.write_text("{}")
    db.write_bytes(b"partial database")
    before = [p.read_bytes() for p in (source, backup, db)]
    result = inspect_migration_integrity_status(source, backup, db)
    assert result["database"] == "incomplete_or_invalid"
    assert result["integrity"] == "unverified"
    assert [p.read_bytes() for p in (source, backup, db)] == before


def test_changed_source_is_not_verified_even_if_database_complete(tmp_path):
    source, backup, db = _paths(tmp_path)
    source.write_text("{}")
    create_offline_migration_snapshot(source, backup, db)
    source.write_text("{ }")
    result = inspect_migration_integrity_status(source, backup, db)
    assert result["source_backup"] == "different"
    assert result["integrity"] == "unverified"
