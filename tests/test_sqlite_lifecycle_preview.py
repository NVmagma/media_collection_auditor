"""Disposable lifecycle preview never grants media-action authorization."""

import json
from datetime import datetime

import pytest

from app.sqlite_lifecycle_preview import preview_isolated_lifecycle, preview_tracked_lifecycle
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS


def _artifacts(tmp_path):
    source, backup, database = (tmp_path / name for name in (
        "state.json", "backup.json", "state.db"
    ))
    state = {section: {} for section in SECTIONS}
    state["first_seen"]["DISPOSABLE/Example"] = "2024-01-01T00:00:00"
    source.write_text(json.dumps(state))
    backup.write_bytes(source.read_bytes())
    write_offline_snapshot(state, database)
    return source, backup, database


@pytest.mark.parametrize("stage,age,signals,expected", [
    ("Waiting", 100, None, "unknown"),
    ("Waiting", 100, {"protected": True}, "keep"),
    ("Waiting", 100, {"keep": True}, "keep"),
    ("Waiting", 100, {"disliked": True}, "hold"),
    ("Holding", 100, None, "unknown"),
    ("Holding", 100, {"favorite": True}, "rescue"),
    ("Holding", 100, {}, "to_removal"),
    ("Removal", 100, None, "delete_candidate"),
])
def test_preview_is_advisory_and_does_not_write(tmp_path, stage, age, signals, expected):
    source, backup, database = _artifacts(tmp_path)
    before = (source.read_bytes(), backup.read_bytes(), database.read_bytes())
    report = preview_isolated_lifecycle(
        source, backup, database, stage=stage, age_days=age,
        wait_days=7, signals=signals,
    )
    assert report["decision"] == expected
    assert report["authorization"] == "not_authorized"
    assert report["production_activation"] == "disabled"
    assert report["storage_authority"] == "json"
    assert before == (source.read_bytes(), backup.read_bytes(), database.read_bytes())


def test_preview_rejects_divergent_backup(tmp_path):
    source, backup, database = _artifacts(tmp_path)
    backup.write_text("{}")
    with pytest.raises(RuntimeError):
        preview_isolated_lifecycle(
            source, backup, database, stage="Waiting", age_days=100,
            wait_days=7, signals={},
        )


@pytest.mark.parametrize("stage,section,signals,expected", [
    ("Waiting", "first_seen", {"keep": True}, "keep"),
    ("Waiting", "first_seen", {"disliked": True}, "hold"),
    ("Holding", "queued", {"favorite": True}, "rescue"),
    ("Holding", "queued", {}, "to_removal"),
    ("Removal", "in_removal", {}, "delete_candidate"),
    ("Removal", "in_removal", None, "unknown"),
])
def test_tracked_preview_uses_persisted_stage_clock(
    tmp_path, stage, section, signals, expected
):
    source, backup, database = _artifacts(tmp_path)
    state = {key: {} for key in SECTIONS}
    state[section]["DISPOSABLE/Example"] = "2024-01-01T00:00:00"
    source.write_text(json.dumps(state))
    backup.write_bytes(source.read_bytes())
    database.unlink()
    write_offline_snapshot(state, database)
    before = (source.read_bytes(), backup.read_bytes(), database.read_bytes())
    report = preview_tracked_lifecycle(
        source, backup, database, media_key="DISPOSABLE/Example",
        stage=stage, wait_days=7, signals=signals,
        now=datetime(2024, 2, 1),
    )
    assert report["decision"] == expected
    assert report["authorization"] == "not_authorized"
    assert before == (source.read_bytes(), backup.read_bytes(), database.read_bytes())


def test_tracked_preview_missing_clock_is_unknown(tmp_path):
    source, backup, database = _artifacts(tmp_path)
    report = preview_tracked_lifecycle(
        source, backup, database, media_key="DISPOSABLE/Missing",
        stage="Removal", wait_days=7, signals={},
        now=datetime(2024, 2, 1),
    )
    assert report["decision"] == "unknown"


def test_tracked_preview_future_clock_is_unknown(tmp_path):
    source, backup, database = _artifacts(tmp_path)
    report = preview_tracked_lifecycle(
        source, backup, database, media_key="DISPOSABLE/Example",
        stage="Waiting", wait_days=7, signals={},
        now=datetime(2023, 1, 1),
    )
    assert report["decision"] == "unknown"


@pytest.mark.parametrize("key,stage,days", [
    ("", "Waiting", 7),
    ("DISPOSABLE/Example", "Keep", 7),
    ("DISPOSABLE/Example", "Waiting", -1),
])
def test_tracked_preview_rejects_invalid_request(tmp_path, key, stage, days):
    source, backup, database = _artifacts(tmp_path)
    with pytest.raises(ValueError):
        preview_tracked_lifecycle(
            source, backup, database, media_key=key,
            stage=stage, wait_days=days, signals={},
        )
