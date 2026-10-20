from datetime import datetime

import pytest

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_collection_decision_preview import preview_collection
from app.sqlite_guarded_move_plan import plan_guarded_moves
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_stale_plan_review import review_plan_again
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore

NOW = datetime(2026, 10, 1, 12)
LIMITS = {"Waiting": 30, "Holding": 7, "Removal": 7, "Keep": 0}


def setup(tmp_path):
    state = {section: {} for section in SECTIONS}
    state["first_seen"]["Movie"] = "2026-08-01T12:00:00"
    db = tmp_path / "state.db"
    write_offline_snapshot(state, db)
    return db


def plan(db, signals):
    return plan_guarded_moves(preview_collection(
        database=db, now=NOW, thresholds=LIMITS,
        signals_by_key={"Movie": signals}))


def recheck(db, original, signals):
    return review_plan_again(
        database=db, original_plan=original, now=NOW,
        thresholds=LIMITS, signals_by_key={"Movie": signals})


def test_unchanged_plan_remains_advisory_only(tmp_path):
    db = setup(tmp_path)
    original = plan(db, {})
    before = db.read_bytes()
    result = recheck(db, original, {})
    assert result["status"] == "unchanged_advisory_only"
    assert result["authorization"] == "not_authorized"
    assert result["fresh_jellyfin_verification"] == "not_established"
    assert db.read_bytes() == before


def test_stale_revision_rejected_even_when_decision_unchanged(tmp_path):
    db = setup(tmp_path)
    original = plan(db, {})
    session = RevisionedAuditSession(GuardedSQLiteStateStore(db))
    session.state["unrelated"] = {"value": 1}
    session.checkpoint()
    result = recheck(db, original, {})
    assert result["status"] == "blocked"
    assert "sqlite_revision_changed" in result["blockers"]


def test_changed_jellyfin_signals_reject_original_plan(tmp_path):
    db = setup(tmp_path)
    original = plan(db, {})
    result = recheck(db, original, {"keep": True})
    assert "lifecycle_plan_changed" in result["blockers"]


def test_unavailable_jellyfin_rejects_previous_candidate(tmp_path):
    db = setup(tmp_path)
    original = plan(db, {})
    result = review_plan_again(database=db, original_plan=original,
                               now=NOW, thresholds=LIMITS, signals_by_key={})
    assert "lifecycle_plan_changed" in result["blockers"]


def test_untrusted_plan_contract_is_rejected(tmp_path):
    db = setup(tmp_path)
    original = plan(db, {})
    original["authorization"] = "authorized"
    with pytest.raises(ValueError, match="Untrusted"):
        recheck(db, original, {})
