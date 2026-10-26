"""Filesystem move inspection must remain conservative and read-only."""

import json

import pytest

from app.sqlite_audit_bootstrap import open_isolated_sqlite_audit
from app.sqlite_migration import create_offline_migration_snapshot
from app.sqlite_operation_coordinator import SQLiteOperationCoordinator
from app.sqlite_recovery_filesystem import inspect_pending_move_filesystem
from app.state_store import GuardedSQLiteStateStore


def prepared(tmp_path):
    source, backup, db = (
        tmp_path / "source.json", tmp_path / "backup.json", tmp_path / "audit.db"
    )
    source.write_text(json.dumps({"retained": True}))
    create_offline_migration_snapshot(source, backup, db)
    session = open_isolated_sqlite_audit(source, backup, db)
    waiting, keep = tmp_path / "Waiting" / "Movie", tmp_path / "Keep" / "Movie"
    waiting.parent.mkdir()
    keep.parent.mkdir()
    SQLiteOperationCoordinator(session).begin("move-1", "move", {
        "source": str(waiting), "destination": str(keep),
        "jellyfin_item_id": "secret-item", "jellyfin_type": "Movie",
    })
    return source, backup, db, waiting, keep


@pytest.mark.parametrize("source_exists,dest_exists,expected", [
    (True, False, "source_only"),
    (False, True, "destination_only_unverified"),
    (True, True, "both_present_ambiguous"),
    (False, False, "both_missing"),
])
def test_move_directory_outcomes_are_never_authorized(
    tmp_path, source_exists, dest_exists, expected,
):
    source, backup, db, waiting, keep = prepared(tmp_path)
    if source_exists:
        waiting.mkdir()
    if dest_exists:
        keep.mkdir()
    before = GuardedSQLiteStateStore(db).load_with_revision()
    result = inspect_pending_move_filesystem(db)
    assert result["interpretation"] == expected
    assert result["authorization"] == "not_authorized"
    assert result["status"] == "blocked"
    assert result["external_verification"] == "filesystem_only_incomplete"
    assert "Waiting" not in str(result)
    assert "Keep" not in str(result)
    assert "secret-item" not in str(result)
    assert GuardedSQLiteStateStore(db).load_with_revision() == before
    assert source.read_bytes() == backup.read_bytes()


def test_symlink_is_not_followed(tmp_path):
    _, _, db, waiting, keep = prepared(tmp_path)
    waiting.mkdir()
    keep.symlink_to(waiting, target_is_directory=True)
    result = inspect_pending_move_filesystem(db)
    assert result["destination_status"] == "symlink_unsafe"
    assert result["interpretation"] == "inspection_incomplete"


def test_file_is_not_accepted_as_media_directory(tmp_path):
    _, _, db, waiting, keep = prepared(tmp_path)
    waiting.write_text("not a directory")
    result = inspect_pending_move_filesystem(db)
    assert result["source_status"] == "not_directory"
    assert result["authorization"] == "not_authorized"


def test_no_pending_move_is_rejected(tmp_path):
    source = tmp_path / "state.json"
    backup = tmp_path / "backup.json"
    db = tmp_path / "audit.db"
    source.write_text("{}")
    create_offline_migration_snapshot(source, backup, db)
    with pytest.raises(RuntimeError, match="Pending move unavailable"):
        inspect_pending_move_filesystem(db)


def test_changed_source_observation_fails_closed(tmp_path, monkeypatch):
    from app import sqlite_recovery_filesystem as module
    _, _, db, waiting, keep = prepared(tmp_path)
    waiting.mkdir()
    original = module._inspect_directory
    counts = {"source": 0}

    def changing(path):
        if path == str(waiting):
            counts["source"] += 1
            if counts["source"] == 2:
                return "missing"
        return original(path)

    monkeypatch.setattr(module, "_inspect_directory", changing)
    result = module.inspect_pending_move_filesystem(db)
    assert result["interpretation"] == "inspection_incomplete"
    assert result["authorization"] == "not_authorized"
    assert result["source_status"] == "unavailable"


def test_changed_destination_observation_fails_closed(tmp_path, monkeypatch):
    from app import sqlite_recovery_filesystem as module
    _, _, db, waiting, keep = prepared(tmp_path)
    waiting.mkdir()
    original = module._inspect_directory
    counts = {"destination": 0}

    def changing(path):
        if path == str(keep):
            counts["destination"] += 1
            if counts["destination"] == 2:
                return "present"
        return original(path)

    monkeypatch.setattr(module, "_inspect_directory", changing)
    result = module.inspect_pending_move_filesystem(db)
    assert result["interpretation"] == "inspection_incomplete"
    assert result["authorization"] == "not_authorized"
    assert result["destination_status"] == "unavailable"


@pytest.mark.parametrize("suffix", ["/../Movie", "/./Movie", "//Movie", "/"])
def test_noncanonical_paths_are_not_treated_as_verified(tmp_path, suffix):
    from app.sqlite_recovery_filesystem import _inspect_directory
    directory = tmp_path / "Movie"
    directory.mkdir()
    result = _inspect_directory(str(tmp_path) + suffix)
    assert result == "invalid_path"


def test_canonical_directory_still_observed(tmp_path):
    from app.sqlite_recovery_filesystem import _inspect_directory
    directory = tmp_path / "Movie"
    directory.mkdir()
    assert _inspect_directory(str(directory)) == "present"
