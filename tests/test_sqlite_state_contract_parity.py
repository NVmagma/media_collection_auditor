"""Representative JSON-to-SQLite state-contract tests on disposable artifacts.

These tests assert lossless preservation, not production SQLite activation.
Jellyfin protection metadata is deliberately treated as opaque historical data:
persisting a flag does NOT constitute a fresh trusted protection check.
"""

import json

import pytest

from app.sqlite_integrity import verify_migration_integrity
from app.sqlite_migration import create_offline_migration_snapshot
from app.sqlite_state import read_snapshot


def _representative_state():
    return {
        "first_seen": {
            "Movies/Example (2024)": "2024-01-01T02:03:04",
            "Shows/Example/Season 01": "2024-01-02T03:04:05",
            "Shows/Example/Season 02": "2024-01-03T04:05:06",
        },
        "queued": {
            "Movies/Leaving (2023)": "2024-02-01T00:00:00",
        },
        "in_removal": {
            "Shows/Archive/Season 03": "2024-03-01T00:00:00",
        },
        "keep_seen": {
            "Movies/Protected (2020)": "2024-04-01T00:00:00",
            "Shows/Protected/Season 01": "2024-04-02T00:00:00",
            "Shows/Protected/Season 02": "2024-04-03T00:00:00",
        },
        "arr_sync_pending": {
            "Movies/Protected (2020)": {
                "stage": "keep", "root": "/media/Movies_keep",
                "monitored": False, "attempts": 3,
                "last_error": "disposable example",
            },
            "Shows/Example/Season 01": {
                "stage": "holding", "root": "/media/Shows_holding",
                "monitored": True, "attempts": 1,
            },
        },
        "legacy_history": {
            "movie": {"notes": ["café", None, True], "id": 123},
            "tv": {"seasons": ["01", "02"], "title": "Example"},
        },
        "jellyfin_protection_history": {
            "Shows/Protected": ["keep-forever", "keep-all-seasons"],
            "Movies/Protected (2020)": ["keep", "favorite"],
            "Movies/Leaving (2023)": ["not-at-all"],
        },
    }


def _artifacts(tmp_path, state):
    source, backup, database = (
        tmp_path / name for name in ("state.json", "backup.json", "state.db")
    )
    source.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    create_offline_migration_snapshot(source, backup, database)
    return source, backup, database


def test_representative_movie_and_tv_contract_round_trips_without_writes(tmp_path):
    expected = _representative_state()
    source, backup, database = _artifacts(tmp_path, expected)
    original = [path.read_bytes() for path in (source, backup, database)]

    verify_migration_integrity(source, backup, database)
    assert read_snapshot(database) == expected
    assert [path.read_bytes() for path in (source, backup, database)] == original

    assert set(read_snapshot(database)["keep_seen"]) == set(expected["keep_seen"])
    assert read_snapshot(database)["arr_sync_pending"] == expected["arr_sync_pending"]
    assert read_snapshot(database)["jellyfin_protection_history"] == (
        expected["jellyfin_protection_history"]
    )


@pytest.mark.parametrize("field", [
    "first_seen", "queued", "in_removal", "keep_seen",
    "arr_sync_pending", "legacy_history", "jellyfin_protection_history",
])
def test_contract_detects_modified_section_or_metadata(tmp_path, field):
    state = _representative_state()
    source, backup, database = _artifacts(tmp_path, state)
    changed = _representative_state()
    if field in ("first_seen", "queued", "in_removal", "keep_seen"):
        key = next(iter(changed[field]))
        changed[field][key] = "2024-05-01T00:00:00"
    elif field == "arr_sync_pending":
        changed[field]["Movies/Protected (2020)"]["attempts"] = 999
    else:
        changed[field] = {"unexpected": "modified"}
    source.write_text(json.dumps(changed, ensure_ascii=False))
    with pytest.raises(RuntimeError, match="Source JSON differs"):
        verify_migration_integrity(source, backup, database)


def test_empty_optional_sections_are_preserved(tmp_path):
    state = {
        "first_seen": {"Movies/Only": "2024-01-01T00:00:00"},
        "legacy_history": {"unknown": {"nested": [1, False, None]}},
    }
    source, backup, database = _artifacts(tmp_path, state)
    verify_migration_integrity(source, backup, database)
    stored = read_snapshot(database)
    for section in ("queued", "in_removal", "keep_seen", "arr_sync_pending"):
        assert stored[section] == {}
    assert stored["legacy_history"] == state["legacy_history"]


def test_season_keys_remain_distinct(tmp_path):
    state = _representative_state()
    source, backup, database = _artifacts(tmp_path, state)
    stored = read_snapshot(database)
    assert stored["first_seen"]["Shows/Example/Season 01"] != (
        stored["first_seen"]["Shows/Example/Season 02"]
    )
    assert "Shows/Protected/Season 01" in stored["keep_seen"]
    assert "Shows/Protected/Season 02" in stored["keep_seen"]
