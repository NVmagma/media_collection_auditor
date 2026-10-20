"""Multi-title SQLite lifecycle rehearsal uses only disposable artifacts."""

import json
from datetime import datetime

import pytest

from app.sqlite_lifecycle_rehearsal import rehearse_isolated_lifecycle
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS


def _fixtures(tmp_path):
    source, backup, database = (
        tmp_path / name for name in ("state.json", "backup.json", "state.db")
    )
    state = {section: {} for section in SECTIONS}
    state["first_seen"]["DISPOSABLE/Protected"] = "2024-01-01T00:00:00"
    state["first_seen"]["DISPOSABLE/Disliked"] = "2024-01-01T00:00:00"
    state["queued"]["DISPOSABLE/Rescue"] = "2024-01-01T00:00:00"
    state["queued"]["DISPOSABLE/Expired"] = "2024-01-01T00:00:00"
    state["in_removal"]["DISPOSABLE/Candidate"] = "2024-01-01T00:00:00"
    state["in_removal"]["DISPOSABLE/Unknown"] = "2024-01-01T00:00:00"
    source.write_text(json.dumps(state))
    backup.write_bytes(source.read_bytes())
    write_offline_snapshot(state, database)
    return source, backup, database


def _title(name, stage, signals):
    return {
        "media_key": "DISPOSABLE/" + name,
        "stage": stage,
        "wait_days": 7,
        "signals": signals,
    }


def test_multiple_titles_one_read_only_snapshot(tmp_path, monkeypatch):
    source, backup, database = _fixtures(tmp_path)
    before = (source.read_bytes(), backup.read_bytes(), database.read_bytes())
    import app.sqlite_lifecycle_rehearsal as module

    original = module.inspect_isolated_audit_state
    calls = []
    def inspect(*args):
        calls.append(1)
        return original(*args)
    monkeypatch.setattr(module, "inspect_isolated_audit_state", inspect)
    result = rehearse_isolated_lifecycle(
        source, backup, database, now=datetime(2024, 2, 1),
        titles=[
            _title("Protected", "Waiting", {"protected": True}),
            _title("Disliked", "Waiting", {"disliked": True}),
            _title("Rescue", "Holding", {"favorite": True}),
            _title("Expired", "Holding", {}),
            _title("Candidate", "Removal", {}),
            _title("Unknown", "Removal", None),
            _title("Missing", "Removal", {}),
        ],
    )
    assert len(calls) == 1
    assert [row["decision"] for row in result["titles"]] == [
        "keep", "hold", "rescue", "to_removal", "delete_candidate",
        "unknown", "unknown",
    ]
    assert all(row["authorization"] == "not_authorized" for row in result["titles"])
    assert result["authorization"] == "not_authorized"
    assert result["production_activation"] == "disabled"
    assert result["storage_authority"] == "json"
    assert result["revision"] == 0
    assert before == (source.read_bytes(), backup.read_bytes(), database.read_bytes())


@pytest.mark.parametrize("titles", [
    [_title("Protected", "Waiting", {}), _title("Protected", "Holding", {})],
    [_title("Protected", "Keep", {})],
    [_title("Protected", "Waiting", "unknown")],
    [{"media_key": "", "stage": "Waiting", "wait_days": 7}],
    [{"media_key": "DISPOSABLE/Protected", "stage": "Waiting", "wait_days": -1}],
])
def test_invalid_rehearsal_input_is_rejected(tmp_path, titles):
    source, backup, database = _fixtures(tmp_path)
    with pytest.raises(ValueError):
        rehearse_isolated_lifecycle(
            source, backup, database, titles=titles, now=datetime(2024, 2, 1)
        )


def test_mismatched_backup_blocks_whole_rehearsal(tmp_path):
    source, backup, database = _fixtures(tmp_path)
    backup.write_text("{}")
    before = database.read_bytes()
    with pytest.raises(RuntimeError):
        rehearse_isolated_lifecycle(
            source, backup, database,
            titles=[_title("Protected", "Waiting", {"keep": True})],
            now=datetime(2024, 2, 1),
        )
    assert database.read_bytes() == before


def test_future_clock_never_proposes_move(tmp_path):
    source, backup, database = _fixtures(tmp_path)
    result = rehearse_isolated_lifecycle(
        source, backup, database,
        titles=[_title("Protected", "Waiting", {})],
        now=datetime(2023, 1, 1),
    )
    assert result["titles"][0]["decision"] == "unknown"
