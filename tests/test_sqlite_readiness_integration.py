"""Exercise readiness against real disposable JSON backups and SQLite files."""

import json

from app.sqlite_migration import create_offline_migration_snapshot
from app.sqlite_readiness import inspect_sqlite_readiness
from app.state_store import GuardedSQLiteStateStore


def _migrated(tmp_path):
    source = tmp_path / "tracking.json"
    backup = tmp_path / "tracking.backup.json"
    database = tmp_path / "tracking.db"
    state = {
        "first_seen": {"Movie": "2025-01-01T12:00:00"},
        "queued": {}, "in_removal": {}, "keep_seen": {},
        "arr_sync_pending": {},
        "legacy_tracking": {"Movie": {"note": "preserve"}},
    }
    original = json.dumps(state, indent=2).encode("utf-8")
    source.write_bytes(original)
    create_offline_migration_snapshot(source, backup, database)
    return source, backup, database, original, state


def test_real_migration_is_reviewable_without_mutating_artifacts(tmp_path):
    source, backup, database, original, state = _migrated(tmp_path)
    before = database.read_bytes()
    report = inspect_sqlite_readiness(source, backup, database)
    assert report == {
        "ready_for_isolated_review": True,
        "production_activation": "disabled",
        "storage_authority": "json",
        "blockers": [],
        "revision": 0,
    }
    assert source.read_bytes() == backup.read_bytes() == original
    assert database.read_bytes() == before
    assert GuardedSQLiteStateStore(database).load_with_revision()[0] == state


def test_modified_source_reports_backup_mismatch_without_writes(tmp_path):
    source, backup, database, original, _ = _migrated(tmp_path)
    source.write_bytes(original + b" ")
    before = database.read_bytes()
    report = inspect_sqlite_readiness(source, backup, database)
    assert report["blockers"] == ["json_backup_mismatch"]
    assert not report["ready_for_isolated_review"]
    assert backup.read_bytes() == original
    assert database.read_bytes() == before


def test_modified_sqlite_snapshot_reports_mismatch(tmp_path):
    source, backup, database, original, state = _migrated(tmp_path)
    store = GuardedSQLiteStateStore(database)
    store.save_if_revision({**state, "unexpected": True}, 0)
    before = database.read_bytes()
    report = inspect_sqlite_readiness(source, backup, database)
    assert report["blockers"] == ["sqlite_snapshot_mismatch"]
    assert not report["ready_for_isolated_review"]
    assert source.read_bytes() == backup.read_bytes() == original
    assert database.read_bytes() == before


def test_missing_backup_blocks_real_migration_readiness(tmp_path):
    source, backup, database, original, _ = _migrated(tmp_path)
    backup.unlink()
    before = database.read_bytes()
    report = inspect_sqlite_readiness(source, backup, database)
    assert report["blockers"] == ["migration_artifact_missing"]
    assert not report["ready_for_isolated_review"]
    assert source.read_bytes() == original
    assert database.read_bytes() == before
