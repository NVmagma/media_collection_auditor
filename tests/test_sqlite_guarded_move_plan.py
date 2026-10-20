from datetime import datetime

import pytest

from app.sqlite_collection_decision_preview import preview_collection
from app.sqlite_guarded_move_plan import plan_guarded_moves
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS

NOW = datetime(2026, 10, 1, 12)
LIMITS = {"Waiting": 30, "Holding": 7, "Removal": 7, "Keep": 0}


def prepare(tmp_path):
    state = {section: {} for section in SECTIONS}
    state["first_seen"].update({
        "Movie Hold": "2026-08-01T12:00:00",
        "Movie Keep": "2026-09-30T12:00:00",
        "Unknown": "2026-08-01T12:00:00",
    })
    state["queued"].update({
        "Movie Removal": "2026-09-01T12:00:00",
        "Movie Rescue": "2026-09-01T12:00:00",
    })
    state["in_removal"]["Deletion Candidate"] = "2026-09-01T12:00:00"
    state["keep_seen"]["TV/Forever"] = "2026-09-01T12:00:00"
    db = tmp_path / "state.db"
    write_offline_snapshot(state, db)
    return db, state


def preview(db, signals):
    return preview_collection(database=db, now=NOW, thresholds=LIMITS,
                              signals_by_key=signals)


def test_end_to_end_plan_maps_only_advisory_move_candidates(tmp_path):
    db, _ = prepare(tmp_path)
    before = db.read_bytes()
    report = plan_guarded_moves(preview(db, {
        "Movie Hold": {},
        "Movie Keep": {"keep": True},
        "Movie Removal": {},
        "Movie Rescue": {"protected": True},
        "Deletion Candidate": {},
        "TV/Forever": {"protected": True},
    }))
    by_key = {row["media_key"]: row for row in report["rows"]}
    assert report["candidate_moves"] == 4
    assert by_key["Movie Hold"]["destination_stage"] == "Holding"
    assert by_key["Movie Keep"]["destination_stage"] == "Keep"
    assert by_key["Movie Removal"]["destination_stage"] == "Removal"
    assert by_key["Movie Rescue"]["destination_stage"] == "Keep"
    assert by_key["Unknown"]["destination_stage"] is None
    assert by_key["Deletion Candidate"]["destination_stage"] is None
    assert by_key["TV/Forever"]["destination_stage"] is None
    assert all(row["authorization"] == "not_authorized" for row in report["rows"])
    assert all(row["required_checks"] for row in report["rows"]
               if row["destination_stage"] is not None)
    assert report["production_activation"] == "disabled"
    assert db.read_bytes() == before


def test_unresolved_intent_prevents_all_plans(tmp_path):
    db, state = prepare(tmp_path)
    state["sqlite_pending_operations"] = {"id": "pending"}
    other = tmp_path / "pending.db"
    write_offline_snapshot(state, other)
    report = plan_guarded_moves(preview(other, {"Movie Hold": {}}))
    assert report["candidate_moves"] == 0


def test_conflicting_clocks_are_not_planned(tmp_path):
    db, state = prepare(tmp_path)
    state["queued"]["Movie Hold"] = "2026-09-01T12:00:00"
    other = tmp_path / "conflict.db"
    write_offline_snapshot(state, other)
    report = plan_guarded_moves(preview(other, {"Movie Hold": {}}))
    row = next(row for row in report["rows"] if row["media_key"] == "Movie Hold")
    assert row["destination_stage"] is None


def test_rejects_forged_authorized_preview():
    with pytest.raises(ValueError):
        plan_guarded_moves({"read_only": True, "authorization": "authorized",
                            "production_activation": "disabled",
                            "revision": 1, "tracked_titles": 0, "decisions": []})


def test_rejects_duplicate_rows():
    row = {"media_key": "Movie", "tracked_stages": ["Waiting"],
           "candidate_action": "hold", "status": "advisory",
           "blockers": [], "authorization": "not_authorized",
           "read_only": True}
    preview_data = {"read_only": True, "authorization": "not_authorized",
                    "production_activation": "disabled", "revision": 1,
                    "tracked_titles": 2, "decisions": [row, row]}
    with pytest.raises(ValueError, match="duplicate"):
        plan_guarded_moves(preview_data)
