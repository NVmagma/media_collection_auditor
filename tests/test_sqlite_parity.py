"""Offline JSON/SQLite parity checks do not authorize storage cutover."""
import json
from pathlib import Path

from app.sqlite_parity import compare_tracking_snapshots


def test_missing_snapshots_block(tmp_path):
    report = compare_tracking_snapshots(tmp_path / "state.json", tmp_path / "state.db")
    assert report == {"status": "blocked", "authorization": "not_authorized",
                      "reason": "snapshot_unavailable_or_invalid"}


def test_invalid_json_blocks(tmp_path):
    source = tmp_path / "state.json"
    source.write_text("{invalid", encoding="utf-8")
    report = compare_tracking_snapshots(source, tmp_path / "state.db")
    assert report["status"] == "blocked"


def test_valid_json_without_database_blocks(tmp_path):
    source = tmp_path / "state.json"
    state = {key: {} for key in ("first_seen", "queued", "in_removal",
                                 "keep_seen", "arr_sync_pending")}
    source.write_text(json.dumps(state), encoding="utf-8")
    report = compare_tracking_snapshots(source, tmp_path / "state.db")
    assert report["status"] == "blocked"
    assert not (tmp_path / "state.db").exists()
