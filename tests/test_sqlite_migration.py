"""Offline JSON backup safety tests; never touch production state."""

import json

import pytest

from app.sqlite_migration import prepare_json_backup, create_offline_migration_snapshot
from app.sqlite_state import read_snapshot


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


def test_offline_conversion_preserves_json_and_state(tmp_path):
    source, backup, database = (
        tmp_path / "state.json", tmp_path / "state.backup.json",
        tmp_path / "snapshot.db"
    )
    state = {
        "first_seen": {"Movie": "2025-01-01T12:00:00"},
        "queued": {}, "in_removal": {}, "keep_seen": {},
        "arr_sync_pending": {
            "Movie": {"stage": "keep", "root": "/media/Movies_keep", "monitored": True}
        },
    }
    original = json.dumps(state, indent=2).encode()
    source.write_bytes(original)
    create_offline_migration_snapshot(source, backup, database)
    assert source.read_bytes() == backup.read_bytes() == original
    assert read_snapshot(database) == state


def test_unknown_historical_fields_are_not_silently_dropped(tmp_path):
    source, backup, database = (
        tmp_path / "state.json", tmp_path / "backup.json",
        tmp_path / "snapshot.db"
    )
    source.write_text('{"legacy":{"Movie":"historical tracking"}}')
    create_offline_migration_snapshot(source, backup, database)
    assert backup.read_bytes() == source.read_bytes()
    assert read_snapshot(database)["legacy"] == {"Movie": "historical tracking"}


def test_existing_destination_blocks_backup_creation(tmp_path):
    source, backup, database = (
        tmp_path / "state.json", tmp_path / "backup.json",
        tmp_path / "snapshot.db"
    )
    source.write_text("{}")
    database.write_bytes(b"existing snapshot")
    with pytest.raises(RuntimeError, match="already exists"):
        create_offline_migration_snapshot(source, backup, database)
    assert not backup.exists()
    assert database.read_bytes() == b"existing snapshot"


def test_overlapping_paths_fail_before_writes(tmp_path):
    source = tmp_path / "state.json"
    source.write_text("{}")
    with pytest.raises(RuntimeError, match="distinct"):
        create_offline_migration_snapshot(source, tmp_path / "backup.json", source)
    assert source.read_text() == "{}"


@pytest.mark.parametrize("variant", ["empty", "lifecycle", "arr_retry", "legacy"])
def test_offline_migration_roundtrip_and_json_rollback_parity(tmp_path, variant):
    """Migration is a copy: restoring authority means retaining original JSON."""
    from app.sqlite_json import parse_unique_json
    from app.sqlite_state import SECTIONS
    source, backup, database = (
        tmp_path / "state.json", tmp_path / "backup.json",
        tmp_path / "snapshot.db",
    )
    states = {
        "empty": {},
        "lifecycle": {
            "first_seen": {"Movie A": "2025-01-01T01:02:03"},
            "queued": {"Show B": "2025-02-02T02:03:04"},
            "in_removal": {"Movie C": "2025-03-03T03:04:05"},
            "keep_seen": {"Show D": "2025-04-04T04:05:06"},
        },
        "arr_retry": {
            "arr_sync_pending": {
                "Movie E": {"stage": "keep", "root": "/media/Movies_keep",
                            "monitored": False},
                "Show F": {"stage": "holding", "root": "/media/TV_holding",
                           "monitored": True},
            },
        },
        "legacy": {"legacy": {"unknown": [1, 2, {"nested": True}]},
                   "last_scan": "2025-06-01T00:00:00"},
    }
    raw = json.dumps(states[variant], indent=2, ensure_ascii=False).encode() + b"\n"
    source.write_bytes(raw)
    create_offline_migration_snapshot(source, backup, database)
    expected = parse_unique_json(raw)
    for section in SECTIONS:
        expected.setdefault(section, {})
    assert read_snapshot(database) == expected
    assert source.read_bytes() == backup.read_bytes() == raw
    # Offline rollback must not require writing or reading SQLite:
    # the original byte-for-byte JSON remains available.
    database.rename(tmp_path / "snapshot.disabled")
    assert source.read_bytes() == backup.read_bytes() == raw
    assert parse_unique_json(backup.read_bytes()) == states[variant]


def test_offline_migration_rejects_changed_source_before_conversion(
    tmp_path, monkeypatch,
):
    from app import sqlite_migration
    source, backup, database = (
        tmp_path / "state.json", tmp_path / "backup.json",
        tmp_path / "snapshot.db",
    )
    source.write_bytes(b'{"legacy":{"version":1}}')
    original = sqlite_migration.prepare_json_backup

    def tamper_after_backup(src, dst):
        result = original(src, dst)
        source.write_bytes(b'{"legacy":{"version":2}}')
        return result

    monkeypatch.setattr(sqlite_migration, "prepare_json_backup", tamper_after_backup)
    with pytest.raises(RuntimeError, match="changed after backup"):
        create_offline_migration_snapshot(source, backup, database)
    assert backup.read_bytes() == b'{"legacy":{"version":1}}'
    assert source.read_bytes() == b'{"legacy":{"version":2}}'
    assert not database.exists()


def test_offline_migration_rejects_invalid_duplicate_keys_without_backup(tmp_path):
    source, backup, database = (
        tmp_path / "state.json", tmp_path / "backup.json",
        tmp_path / "snapshot.db",
    )
    source.write_bytes(b'{"queued":{},"queued":{"Movie":"2025-01-01T00:00:00"}}')
    with pytest.raises(RuntimeError):
        create_offline_migration_snapshot(source, backup, database)
    assert not backup.exists()
    assert not database.exists()
