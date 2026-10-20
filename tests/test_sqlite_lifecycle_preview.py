"""Disposable lifecycle preview never grants media-action authorization."""

import json

import pytest

from app.sqlite_lifecycle_preview import preview_isolated_lifecycle
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
