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


def test_sqlite_transition_survives_separate_python_process(tmp_path):
    """A fresh interpreter sees committed Keep state and unchanged JSON."""
    import os
    import subprocess
    import sys
    from app.sqlite_migration import create_offline_migration_snapshot
    from app.sqlite_store import SQLiteStateStore

    source, backup, database = (tmp_path / "state.json",
                                tmp_path / "backup.json", tmp_path / "state.db")
    state = {"first_seen": {"Movies/Example": "2024-01-01T00:00:00"}}
    source.write_text(json.dumps(state), encoding="utf-8")
    create_offline_migration_snapshot(source, backup, database)
    store = SQLiteStateStore(database)
    snapshot, revision = store.load_with_revision()
    snapshot["keep_seen"]["Movies/Example"] = snapshot["first_seen"].pop("Movies/Example")
    store.save_if_revision(snapshot, revision)

    # A separate interpreter simulates a process restart, without touching media.
    program = (
        "import json,sys; from app.sqlite_store import SQLiteStateStore; "
        "state,revision=SQLiteStateStore(sys.argv[1]).load_with_revision(); "
        "print(json.dumps({'revision':revision,'waiting':len(state['first_seen']),"
        "'keep':len(state['keep_seen'])}))"
    )
    root = str(Path(__file__).resolve().parents[1])
    env = dict(os.environ, PYTHONPATH=root, PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run([sys.executable, "-c", program, str(database)],
                            cwd=root, env=env, check=True, capture_output=True,
                            text=True, timeout=15)
    assert json.loads(result.stdout) == {"revision": revision + 1,
                                          "waiting": 0, "keep": 1}
    assert backup.read_bytes() == source.read_bytes()
    assert compare_tracking_snapshots(source, database)["status"] == "mismatch"


def test_stale_writer_after_restart_cannot_overwrite_keep(tmp_path):
    import pytest
    from app.sqlite_snapshot_writer import write_offline_snapshot
    from app.sqlite_state import SECTIONS
    from app.sqlite_store import SQLiteStateStore

    database = tmp_path / "state.db"
    write_offline_snapshot({section: {} for section in SECTIONS}, database)
    old = SQLiteStateStore(database)
    stale_state, stale_revision = old.load_with_revision()
    new = SQLiteStateStore(database)
    updated, revision = new.load_with_revision()
    updated["keep_seen"]["Movies/Example"] = "2024-01-01T00:00:00"
    new.save_if_revision(updated, revision)
    stale_state["first_seen"]["Movies/Example"] = "2024-01-01T00:00:00"
    with pytest.raises(RuntimeError, match="Stale SQLite state revision"):
        old.save_if_revision(stale_state, stale_revision)
    assert SQLiteStateStore(database).load() == updated
