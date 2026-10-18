"""Restart-boundary checks for persistent offline migration artifacts."""

import json
import os
from pathlib import Path
import subprocess
import sys

from app.sqlite_migration import create_offline_migration_snapshot
from app.sqlite_recovery import inspect_migration_integrity_status


def _restart_check(source, backup, database):
    """Inspect from a fresh interpreter, as after an auditor container restart."""
    code = (
        "import json,sys; "
        "from app.sqlite_recovery import inspect_migration_integrity_status; "
        "print(json.dumps(inspect_migration_integrity_status(*sys.argv[1:])))"
    )
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    run = subprocess.run(
        [sys.executable, "-c", code, str(source), str(backup), str(database)],
        cwd=root, env=env, capture_output=True, text=True, check=True,
    )
    return json.loads(run.stdout)


def test_verified_snapshot_survives_fresh_process(tmp_path):
    source, backup, database = (
        tmp_path / "state.json", tmp_path / "backup.json", tmp_path / "state.db"
    )
    source.write_text(json.dumps({
        "first_seen": {"Movie": "2024-01-01T01:02:03"},
        "arr_sync_pending": {"Movie": {
            "stage": "keep", "root": "/media/Movies_keep", "monitored": False,
        }},
        "legacy": {"nested": ["preserved", None, True]},
    }))
    create_offline_migration_snapshot(source, backup, database)
    before = [p.read_bytes() for p in (source, backup, database)]
    assert _restart_check(source, backup, database)["integrity"] == "verified"
    assert inspect_migration_integrity_status(source, backup, database)["integrity"] == "verified"
    assert [p.read_bytes() for p in (source, backup, database)] == before


def test_partial_database_remains_unverified_after_restart(tmp_path):
    source, backup, database = (
        tmp_path / "state.json", tmp_path / "backup.json", tmp_path / "state.db"
    )
    source.write_text("{}")
    backup.write_text("{}")
    database.write_bytes(b"partial sqlite write")
    before = [p.read_bytes() for p in (source, backup, database)]
    status = _restart_check(source, backup, database)
    assert status["database"] == "incomplete_or_invalid"
    assert status["integrity"] == "unverified"
    assert [p.read_bytes() for p in (source, backup, database)] == before


def test_missing_backup_remains_unverified_after_restart(tmp_path):
    source, backup, database = (
        tmp_path / "state.json", tmp_path / "backup.json", tmp_path / "state.db"
    )
    source.write_text("{}")
    create_offline_migration_snapshot(source, backup, database)
    backup.unlink()
    before = [p.read_bytes() for p in (source, database)]
    status = _restart_check(source, backup, database)
    assert status["backup"] == "missing"
    assert status["integrity"] == "unverified"
    assert not backup.exists()
    assert [p.read_bytes() for p in (source, database)] == before
