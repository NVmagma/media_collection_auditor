"""Interrupted offline migration rehearsals using disposable tracking state.

No production auditor, service clients or media directories are invoked.
"""

import sqlite3

import pytest

from app.sqlite_audit_preflight import prepare_sqlite_audit_state
from app.sqlite_integrity import verify_migration_integrity
from app.sqlite_migration import create_offline_migration_snapshot
from app.sqlite_recovery_json_rollback import inspect_json_rollback_readiness


def artifacts(tmp_path):
    source, backup, database = (tmp_path / "state.json",
                                tmp_path / "backup.json", tmp_path / "state.db")
    source.write_bytes(b'{"first_seen":{"Film":"2024-01-02T03:04:05"},"legacy":{"x":1}}\n')
    return source, backup, database


def test_interrupted_writer_preserves_json_and_blocks_activation(tmp_path, monkeypatch):
    source, backup, database = artifacts(tmp_path)
    original = source.read_bytes()

    def fail_after_creating_partial_db(_state, destination):
        with sqlite3.connect(destination) as connection:
            connection.execute("CREATE TABLE metadata (key TEXT, value TEXT)")
            connection.execute("INSERT INTO metadata VALUES ('snapshot_complete','0')")
        raise RuntimeError("simulated power loss during SQLite conversion")

    monkeypatch.setattr("app.sqlite_migration.write_offline_snapshot",
                        fail_after_creating_partial_db)
    with pytest.raises(RuntimeError, match="simulated power loss"):
        create_offline_migration_snapshot(source, backup, database)
    assert source.read_bytes() == backup.read_bytes() == original
    assert database.exists()
    assert inspect_json_rollback_readiness(source, backup)["authorization"] == "not_authorized"
    with pytest.raises((RuntimeError, sqlite3.DatabaseError)):
        prepare_sqlite_audit_state(source, backup, database)
    with pytest.raises(RuntimeError, match="already exists"):
        create_offline_migration_snapshot(source, backup, database)
    assert source.read_bytes() == backup.read_bytes() == original


def test_source_changed_after_backup_prevents_sqlite_creation(tmp_path, monkeypatch):
    source, backup, database = artifacts(tmp_path)
    original = source.read_bytes()
    from app import sqlite_migration
    real_backup = sqlite_migration.prepare_json_backup

    def backup_then_change(src, dst):
        result = real_backup(src, dst)
        source.write_bytes(original + b" ")
        return result

    monkeypatch.setattr(sqlite_migration, "prepare_json_backup", backup_then_change)
    with pytest.raises(RuntimeError, match="changed after backup"):
        create_offline_migration_snapshot(source, backup, database)
    assert backup.read_bytes() == original
    assert source.read_bytes() == original + b" "
    assert not database.exists()


def test_incomplete_snapshot_marker_blocks_preflight(tmp_path):
    source, backup, database = artifacts(tmp_path)
    create_offline_migration_snapshot(source, backup, database)
    original = source.read_bytes()
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE metadata SET value = '0' WHERE key = 'snapshot_complete'")
    with pytest.raises(RuntimeError):
        verify_migration_integrity(source, backup, database)
    with pytest.raises(RuntimeError):
        prepare_sqlite_audit_state(source, backup, database)
    assert source.read_bytes() == backup.read_bytes() == original
