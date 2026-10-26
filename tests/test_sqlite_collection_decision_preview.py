from datetime import datetime

import pytest

from app.sqlite_collection_decision_preview import preview_collection
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS

NOW = datetime(2026, 10, 1, 12)
LIMITS = {"Waiting": 30, "Holding": 7, "Removal": 7, "Keep": 0}


def setup_db(tmp_path):
    state = {section: {} for section in SECTIONS}
    state["first_seen"]["Movie A"] = "2026-08-01T12:00:00"
    state["queued"]["Movie B"] = "2026-09-01T12:00:00"
    state["keep_seen"]["TV/Protected"] = "2026-09-01T12:00:00"
    db = tmp_path / "state.db"
    write_offline_snapshot(state, db)
    return db, state


def review(db, signals):
    return preview_collection(database=db, now=NOW, thresholds=LIMITS,
                              signals_by_key=signals)


def test_collection_preview_is_read_only_and_uses_real_decisions(tmp_path):
    db, _ = setup_db(tmp_path)
    before = db.read_bytes()
    result = review(db, {
        "Movie A": {},
        "Movie B": {"keep": True},
        "TV/Protected": {"protected": True, "keep_all": True},
    })
    assert result["tracked_titles"] == 3
    assert result["authorization"] == "not_authorized"
    assert result["production_activation"] == "disabled"
    by_key = {row["media_key"]: row for row in result["decisions"]}
    assert by_key["Movie A"]["candidate_action"] == "hold"
    assert by_key["Movie B"]["candidate_action"] == "rescue"
    assert by_key["TV/Protected"]["candidate_action"] == "none"
    assert db.read_bytes() == before


def test_unknown_jellyfin_blocks_title(tmp_path):
    db, _ = setup_db(tmp_path)
    result = review(db, {"Movie A": {}})
    assert result["blocked_titles"] == 2
    assert all(row["authorization"] == "not_authorized"
               for row in result["decisions"])


def test_duplicate_stage_clock_is_blocked(tmp_path):
    db, state = setup_db(tmp_path)
    state["queued"]["Movie A"] = "2026-09-01T12:00:00"
    duplicate = tmp_path / "duplicate.db"
    write_offline_snapshot(state, duplicate)
    result = review(duplicate, {"Movie A": {}, "Movie B": {},
                                "TV/Protected": {}})
    item = next(row for row in result["decisions"]
                if row["media_key"] == "Movie A")
    assert item["action"] == "none"
    assert "missing_or_conflicting_clock" in item["blockers"]


def test_unresolved_intent_blocks_every_title(tmp_path):
    db, state = setup_db(tmp_path)
    state["sqlite_pending_operations"] = {"id": "unresolved"}
    pending = tmp_path / "pending.db"
    write_offline_snapshot(state, pending)
    result = review(pending, {"Movie A": {}, "Movie B": {},
                              "TV/Protected": {}})
    assert result["status"] == "blocked"
    assert result["blocked_titles"] == 3


def test_missing_database_is_not_initialized(tmp_path):
    missing = tmp_path / "missing.db"
    with pytest.raises(RuntimeError):
        review(missing, {})
    assert not missing.exists()


def test_incomplete_thresholds_rejected(tmp_path):
    db, _ = setup_db(tmp_path)
    with pytest.raises(ValueError):
        preview_collection(database=db, now=NOW, thresholds={"Waiting": 30},
                           signals_by_key={})
