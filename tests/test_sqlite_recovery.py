"""Read-only diagnostics for interrupted SQLite migration artifacts."""

from app.sqlite_recovery import inspect_migration_artifacts
from app.sqlite_snapshot_writer import write_offline_snapshot


def test_no_artifacts_are_created_by_inspection(tmp_path):
    source, backup, db = (tmp_path / "state.json", tmp_path / "backup.json",
                          tmp_path / "state.db")
    assert inspect_migration_artifacts(source, backup, db) == {
        "source": "missing", "backup": "missing",
        "database": "missing", "source_backup": "unverified",
    }
    assert list(tmp_path.iterdir()) == []


def test_incomplete_database_is_preserved(tmp_path):
    source, backup, db = (tmp_path / "state.json", tmp_path / "backup.json",
                          tmp_path / "state.db")
    source.write_text("{}")
    backup.write_text("{}")
    db.write_bytes(b"interrupted sqlite write")
    assert inspect_migration_artifacts(source, backup, db) == {
        "source": "valid", "backup": "valid",
        "database": "incomplete_or_invalid", "source_backup": "identical",
    }
    assert db.read_bytes() == b"interrupted sqlite write"


def test_source_changes_are_detected(tmp_path):
    source, backup, db = (tmp_path / "state.json", tmp_path / "backup.json",
                          tmp_path / "state.db")
    source.write_text("{}")
    backup.write_text("{ }")
    assert inspect_migration_artifacts(source, backup, db)["source_backup"] == "different"


def test_complete_snapshot_is_recognized_without_activation(tmp_path):
    source, backup, db = (tmp_path / "state.json", tmp_path / "backup.json",
                          tmp_path / "state.db")
    source.write_text("{}")
    backup.write_text("{}")
    state = {section: {} for section in (
        "first_seen", "queued", "in_removal", "keep_seen", "arr_sync_pending"
    )}
    write_offline_snapshot(state, db)
    result = inspect_migration_artifacts(source, backup, db)
    assert result["database"] == "complete"
    assert result["source_backup"] == "identical"
    assert source.read_text() == "{}"


def test_invalid_backup_is_reported_without_overwrite(tmp_path):
    source, backup, db = (tmp_path / "state.json", tmp_path / "backup.json",
                          tmp_path / "state.db")
    source.write_text("{}")
    backup.write_bytes(b"invalid backup")
    result = inspect_migration_artifacts(source, backup, db)
    assert result["backup"] == "invalid"
    assert result["source_backup"] == "unverified"
    assert backup.read_bytes() == b"invalid backup"
