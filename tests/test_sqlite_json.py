"""Duplicate JSON keys must never be silently discarded."""

import pytest

from app.sqlite_json import parse_unique_json
from app.sqlite_migration import create_offline_migration_snapshot
from app.sqlite_recovery import inspect_migration_artifacts


@pytest.mark.parametrize("raw", [
    b'{"queued": {}, "queued": {}}',
    b'{"arr_sync_pending": {"item": {"stage": "keep", "stage": "holding"}}}',
    b'{"arr_sync_pending": {"item": {}, "item": {}}}',
])
def test_strict_parser_rejects_duplicate_keys_at_any_depth(raw):
    with pytest.raises(ValueError, match="Duplicate JSON key"):
        parse_unique_json(raw)


def test_duplicate_source_never_creates_backup_or_database(tmp_path):
    source, backup, database = (
        tmp_path / "state.json", tmp_path / "backup.json", tmp_path / "state.db"
    )
    original = b'{"queued": {}, "queued": {"movie": "2025-01-01T00:00:00"}}'
    source.write_bytes(original)
    with pytest.raises(RuntimeError, match="validate or back up"):
        create_offline_migration_snapshot(source, backup, database)
    assert source.read_bytes() == original
    assert not backup.exists()
    assert not database.exists()


def test_recovery_marks_duplicate_backup_invalid(tmp_path):
    source, backup, database = (
        tmp_path / "state.json", tmp_path / "backup.json", tmp_path / "state.db"
    )
    source.write_text("{}")
    original = b'{"queued": {}, "queued": {}}'
    backup.write_bytes(original)
    result = inspect_migration_artifacts(source, backup, database)
    assert result["source"] == "valid"
    assert result["backup"] == "invalid"
    assert result["source_backup"] == "unverified"
    assert backup.read_bytes() == original
