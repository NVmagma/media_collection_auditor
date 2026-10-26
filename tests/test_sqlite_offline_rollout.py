"""End-to-end disposable migration, interruption, readiness, and CLI tests."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app.sqlite_migration import create_offline_migration_snapshot
from app.sqlite_readiness import inspect_sqlite_readiness
from app.sqlite_readiness_cli import main
from app.sqlite_state import SCHEMA_SQL, SCHEMA_VERSION
from app.state_store import GuardedSQLiteStateStore


def _paths(tmp_path):
    return (tmp_path / "state.json", tmp_path / "backup.json",
            tmp_path / "state.db")


def _source(source):
    state = {
        "first_seen": {"Movie": "2024-01-01T01:02:03"},
        "queued": {}, "in_removal": {}, "keep_seen": {},
        "arr_sync_pending": {},
        "legacy": {"movie": {"history": ["waiting", "keep"], "retained": True}},
    }
    original = json.dumps(state, indent=2).encode()
    source.write_bytes(original)
    return original, state


def test_cli_reports_clean_migration_without_writes(tmp_path, capsys):
    source, backup, database = _paths(tmp_path)
    original, _ = _source(source)
    create_offline_migration_snapshot(source, backup, database)
    before = database.read_bytes()
    assert main([str(source), str(backup), str(database)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ready_for_isolated_review"] is True
    assert report["production_activation"] == "disabled"
    assert report["storage_authority"] == "json"
    assert source.read_bytes() == backup.read_bytes() == original
    assert database.read_bytes() == before


def test_cli_reports_missing_backup_and_fails(tmp_path, capsys):
    source, backup, database = _paths(tmp_path)
    _source(source)
    create_offline_migration_snapshot(source, backup, database)
    backup.unlink()
    assert main([str(source), str(backup), str(database)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["blockers"] == ["migration_artifact_missing"]


def test_interrupted_conversion_cannot_be_retried_or_activated(tmp_path, monkeypatch):
    source, backup, database = _paths(tmp_path)
    original, _ = _source(source)

    def interrupted(state, destination):
        destination.write_bytes(b"partial database")
        raise OSError("simulated interrupted write")

    monkeypatch.setattr("app.sqlite_migration.write_offline_snapshot", interrupted)
    with pytest.raises(OSError, match="interrupted"):
        create_offline_migration_snapshot(source, backup, database)
    assert source.read_bytes() == backup.read_bytes() == original
    before = database.read_bytes()
    report = inspect_sqlite_readiness(source, backup, database)
    assert not report["ready_for_isolated_review"]
    assert report["production_activation"] == "disabled"
    with pytest.raises(RuntimeError, match="already exists"):
        create_offline_migration_snapshot(source, backup, database)
    assert database.read_bytes() == before


def test_incomplete_transaction_cannot_be_accepted(tmp_path):
    source, backup, database = _paths(tmp_path)
    original, _ = _source(source)
    backup.write_bytes(original)
    with sqlite3.connect(database) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.execute("INSERT INTO metadata (key, value) VALUES (?, ?)",
                     ("schema_version", str(SCHEMA_VERSION)))
    before = database.read_bytes()
    assert inspect_sqlite_readiness(source, backup, database)["ready_for_isolated_review"] is False
    assert database.read_bytes() == before


def test_historical_tracking_preserved_across_restart_and_failed_readiness(tmp_path):
    source, backup, database = _paths(tmp_path)
    original, state = _source(source)
    create_offline_migration_snapshot(source, backup, database)
    first = GuardedSQLiteStateStore(database)
    persisted, revision = first.load_with_revision()
    assert persisted == state
    assert revision == 0
    del first
    second = GuardedSQLiteStateStore(database)
    assert second.load_with_revision() == (state, 0)
    source.write_bytes(original + b" ")
    report = inspect_sqlite_readiness(source, backup, database)
    assert report["blockers"] == ["json_backup_mismatch"]
    assert second.load_with_revision() == (state, 0)
    assert backup.read_bytes() == original


def test_cli_subprocess_reports_blocked_without_traceback(tmp_path):
    source, backup, database = _paths(tmp_path)
    completed = subprocess.run(
        [sys.executable, "-m", "app.sqlite_readiness_cli",
         str(source), str(backup), str(database)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 1
    assert json.loads(completed.stdout)["production_activation"] == "disabled"
    assert "Traceback" not in completed.stderr
