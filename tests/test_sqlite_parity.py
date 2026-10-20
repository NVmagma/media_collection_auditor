"""Offline JSON/SQLite parity checks do not authorize storage cutover."""
import json
from pathlib import Path

from app.sqlite_parity import compare_tracking_snapshots


def test_missing_snapshots_block(tmp_path):
    report = compare_tracking_snapshots(tmp_path / "state.json", tmp_path / "state.db")
    assert report == {"status": "blocked", "authorization": "not_authorized",
                      "reason": "snapshot_unavailable_or_invalid"}


def test_invalid_json_blocks(tmp_path):
    source = tmp_path / "state.json"
    source.write_text("{invalid", encoding="utf-8")
    report = compare_tracking_snapshots(source, tmp_path / "state.db")
    assert report["status"] == "blocked"


def test_valid_json_without_database_blocks(tmp_path):
    source = tmp_path / "state.json"
    state = {key: {} for key in ("first_seen", "queued", "in_removal",
                                 "keep_seen", "arr_sync_pending")}
    source.write_text(json.dumps(state), encoding="utf-8")
    report = compare_tracking_snapshots(source, tmp_path / "state.db")
    assert report["status"] == "blocked"
    assert not (tmp_path / "state.db").exists()


def test_offline_migration_parity_and_lifecycle_change(tmp_path):
    from app.sqlite_migration import create_offline_migration_snapshot
    from app.sqlite_store import SQLiteStateStore

    source = tmp_path / "state.json"
    backup = tmp_path / "backup.json"
    database = tmp_path / "state.db"
    original = {"first_seen": {"Movies/Example": "2024-01-01T00:00:00"},
                "legacy": {"preserved": True}}
    source.write_text(json.dumps(original), encoding="utf-8")
    create_offline_migration_snapshot(source, backup, database)
    assert compare_tracking_snapshots(source, database)["status"] == "match"

    store = SQLiteStateStore(database)
    state, revision = store.load_with_revision()
    state["keep_seen"]["Movies/Example"] = state["first_seen"].pop("Movies/Example")
    store.save_if_revision(state, revision)
    assert store.load()["keep_seen"]["Movies/Example"] == "2024-01-01T00:00:00"
    assert compare_tracking_snapshots(source, database) == {
        "status": "mismatch", "authorization": "not_authorized",
        "reason": "state_mismatch", "section": "first_seen"}
    assert json.loads(source.read_text()) == original
    assert backup.read_bytes() == source.read_bytes()


def test_legacy_sections_normalized(tmp_path):
    from app.sqlite_migration import create_offline_migration_snapshot
    source, backup, database = (tmp_path / "state.json",
                                tmp_path / "backup.json", tmp_path / "state.db")
    source.write_text('{"legacy":{"x":1}}', encoding="utf-8")
    create_offline_migration_snapshot(source, backup, database)
    assert compare_tracking_snapshots(source, database)["status"] == "match"


def test_duplicate_json_keys_block(tmp_path):
    source = tmp_path / "state.json"
    source.write_text('{"first_seen":{},"first_seen":{}}', encoding="utf-8")
    result = compare_tracking_snapshots(source, tmp_path / "state.db")
    assert result["status"] == "blocked"
