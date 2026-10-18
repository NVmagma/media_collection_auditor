"""Disposable end-to-end bootstrap checks, without media side effects."""

import json

import pytest

from app.sqlite_audit_bootstrap import open_isolated_sqlite_audit
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS


def _setup(tmp_path):
    source = tmp_path / "state.json"
    backup = tmp_path / "backup.json"
    database = tmp_path / "state.db"
    state = {section: {} for section in SECTIONS}
    state["first_seen"]["Movie"] = "2024-01-01T00:00:00"
    state["legacy"] = {"unknown": True}
    source.write_text(json.dumps(state))
    backup.write_bytes(source.read_bytes())
    write_offline_snapshot(state, database)
    return source, backup, database, state


def test_bootstrap_preserves_tracking_and_supports_guarded_checkpoint(tmp_path):
    source, backup, database, original = _setup(tmp_path)
    session = open_isolated_sqlite_audit(source, backup, database)
    assert session.state == original
    assert session.revision == 0
    session.state["arr_sync_pending"]["Movie"] = {
        "stage": "keep", "root": "/media/Movies_keep", "monitored": False
    }
    session.checkpoint()
    assert session.revision == 1
    assert session.state["legacy"] == original["legacy"]


def test_bootstrap_rejects_corrupt_backup_before_any_write(tmp_path):
    source, backup, database, original = _setup(tmp_path)
    backup.write_text("{}")
    with pytest.raises(RuntimeError):
        open_isolated_sqlite_audit(source, backup, database)
    assert source.read_bytes() != backup.read_bytes()


def test_bootstrap_rejects_already_modified_sqlite(tmp_path):
    source, backup, database, _ = _setup(tmp_path)
    session = open_isolated_sqlite_audit(source, backup, database)
    session.checkpoint()
    with pytest.raises(RuntimeError, match="already modified"):
        open_isolated_sqlite_audit(source, backup, database)


def test_bootstrap_rejects_missing_database(tmp_path):
    source, backup, database, _ = _setup(tmp_path)
    database.unlink()
    with pytest.raises(RuntimeError):
        open_isolated_sqlite_audit(source, backup, database)
    assert not database.exists()
