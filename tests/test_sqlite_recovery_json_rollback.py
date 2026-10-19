"""Rollback diagnostics cannot modify authoritative JSON or media."""

import pytest

from app.sqlite_recovery_json_rollback import inspect_json_rollback_readiness


def test_matching_json_is_advisory_only(tmp_path):
    source, backup = tmp_path / "source.json", tmp_path / "backup.json"
    source.write_bytes(b'{"legacy":{"id":"kept"}}\n')
    backup.write_bytes(source.read_bytes())
    before = source.read_bytes()
    report = inspect_json_rollback_readiness(source, backup)
    assert report["reason"] == "matching_json_backup_advisory_only"
    assert report["authorization"] == "not_authorized"
    assert report["restore_performed"] is False
    assert source.read_bytes() == backup.read_bytes() == before
    assert "kept" not in str(report)


def test_divergent_backup_blocks(tmp_path):
    source, backup = tmp_path / "source.json", tmp_path / "backup.json"
    source.write_text('{"first_seen":{}}')
    backup.write_text('{"first_seen":{},"legacy":{}}')
    assert inspect_json_rollback_readiness(source, backup)["reason"] == "json_backup_diverged"


@pytest.mark.parametrize("source_content", ["{bad json", "[]", '{"x":1,"x":2}'])
def test_invalid_state_blocks(tmp_path, source_content):
    source, backup = tmp_path / "source.json", tmp_path / "backup.json"
    source.write_text(source_content)
    backup.write_text(source_content)
    assert inspect_json_rollback_readiness(source, backup)["reason"] == "state_invalid"


def test_missing_backup_blocks(tmp_path):
    source = tmp_path / "source.json"
    source.write_text("{}")
    assert inspect_json_rollback_readiness(source, tmp_path / "missing.json")["reason"] == "state_unavailable"


def test_symlink_backup_blocks(tmp_path):
    source, backup = tmp_path / "source.json", tmp_path / "backup.json"
    source.write_text("{}")
    backup.symlink_to(source)
    assert inspect_json_rollback_readiness(source, backup)["reason"] == "symlink_unsafe"


def test_same_path_blocks(tmp_path):
    source = tmp_path / "source.json"
    source.write_text("{}")
    assert inspect_json_rollback_readiness(source, source)["reason"] == "paths_not_distinct"
