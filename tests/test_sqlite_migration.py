"""Offline JSON backup safety tests; never touch production state."""

import json

import pytest

from app.sqlite_migration import prepare_json_backup


def test_backup_preserves_exact_source_bytes_and_unknown_fields(tmp_path):
    source = tmp_path / "state.json"
    backup = tmp_path / "state.backup.json"
    original = b'{"first_seen":{"Movie":"2025-01-01T12:00:00"},"legacy":{"x":1}}\n'
    source.write_bytes(original)
    state = prepare_json_backup(source, backup)
    assert source.read_bytes() == backup.read_bytes() == original
    assert state["first_seen"]["Movie"] == "2025-01-01T12:00:00"
    assert state["legacy"] == {"x": 1}


def test_invalid_source_never_creates_backup(tmp_path):
    source = tmp_path / "state.json"
    backup = tmp_path / "backup.json"
    source.write_text('{"queued":{"Movie":"2999-01-01T00:00:00"}}')
    with pytest.raises(RuntimeError, match="timestamp"):
        prepare_json_backup(source, backup)
    assert not backup.exists()


def test_existing_backup_never_overwritten(tmp_path):
    source = tmp_path / "state.json"
    backup = tmp_path / "backup.json"
    source.write_text("{}")
    backup.write_bytes(b"important old backup")
    with pytest.raises(RuntimeError, match="already exists"):
        prepare_json_backup(source, backup)
    assert backup.read_bytes() == b"important old backup"


def test_missing_source_fails_closed(tmp_path):
    backup = tmp_path / "backup.json"
    with pytest.raises(RuntimeError, match="missing"):
        prepare_json_backup(tmp_path / "missing.json", backup)
    assert not backup.exists()


def test_source_and_backup_cannot_be_same_file(tmp_path):
    source = tmp_path / "state.json"
    source.write_text("{}")
    with pytest.raises(RuntimeError, match="must not overwrite"):
        prepare_json_backup(source, source)
    assert source.read_text() == "{}"
