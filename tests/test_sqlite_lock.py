"""Tests for cooperating offline migration locks."""

import pytest

from app.sqlite_lock import migration_lock, state_writer_lock
from app.sqlite_migration import create_offline_migration_snapshot
from app.sqlite_state import read_snapshot


def test_second_migration_lock_is_rejected(tmp_path):
    source = tmp_path / "state.json"
    source.write_text("{}")
    with migration_lock(source):
        with pytest.raises(RuntimeError, match="Another offline migration"):
            with migration_lock(source):
                pass


def test_lock_released_after_exception(tmp_path):
    source = tmp_path / "state.json"
    source.write_text("{}")
    with pytest.raises(ValueError):
        with migration_lock(source):
            raise ValueError("simulated failure")
    with migration_lock(source):
        pass


def test_locked_conversion_cannot_create_backup_or_database(tmp_path):
    source = tmp_path / "state.json"
    backup = tmp_path / "backup.json"
    database = tmp_path / "snapshot.db"
    source.write_text("{}")
    with migration_lock(source):
        with pytest.raises(RuntimeError, match="Another offline migration"):
            create_offline_migration_snapshot(source, backup, database)
    assert not backup.exists()
    assert not database.exists()


def test_conversion_creates_snapshot_and_releases_lock(tmp_path):
    source = tmp_path / "state.json"
    backup = tmp_path / "backup.json"
    database = tmp_path / "snapshot.db"
    source.write_text("{}")
    create_offline_migration_snapshot(source, backup, database)
    assert read_snapshot(database)["queued"] == {}
    with migration_lock(source):
        pass


def test_missing_source_does_not_create_lock(tmp_path):
    source = tmp_path / "missing.json"
    with pytest.raises(RuntimeError, match="missing"):
        with migration_lock(source):
            pass
    assert not (tmp_path / "missing.json.migration.lock").exists()


def test_json_writer_is_blocked_by_migration(tmp_path):
    source = tmp_path / "state.json"
    source.write_text("{}")
    with migration_lock(source):
        with pytest.raises(RuntimeError, match="blocked"):
            with state_writer_lock(source):
                pass


def test_migration_is_blocked_by_json_writer(tmp_path):
    source = tmp_path / "state.json"
    source.write_text("{}")
    with state_writer_lock(source):
        with pytest.raises(RuntimeError, match="Another offline migration"):
            with migration_lock(source):
                pass


def test_json_writer_lock_allows_fresh_state_and_releases(tmp_path):
    source = tmp_path / "state.json"
    with state_writer_lock(source):
        source.write_text("{}")
    with migration_lock(source):
        pass
    assert source.read_text() == "{}"


def test_json_writer_lock_releases_after_exception(tmp_path):
    source = tmp_path / "state.json"
    with pytest.raises(ValueError):
        with state_writer_lock(source):
            raise ValueError("simulated interrupted save")
    with state_writer_lock(source):
        pass
