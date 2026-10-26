"""Plan-to-disposable-move parity, without trusted Jellyfin authorization."""

from datetime import datetime

import pytest

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_collection_decision_preview import preview_collection
from app.sqlite_disposable_lifecycle_flow import execute_disposable_lifecycle_move
from app.sqlite_guarded_move_plan import plan_guarded_moves
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore

NOW = datetime(2024, 2, 1)
KEY = "DISPOSABLE/Movie"
LIMITS = {"Waiting": 7, "Holding": 7, "Removal": 7, "Keep": 0}


def lab(tmp_path):
    root = tmp_path / "lab"
    root.mkdir()
    (root / ".sqlite_disposable_rehearsal").write_text("DISPOSABLE ONLY\n")
    for stage in ("transient", "holding", "removal", "keep"):
        (root / stage).mkdir()
    (root / "transient" / "Movie").mkdir()
    state = {section: {} for section in SECTIONS}
    state["first_seen"][KEY] = "2024-01-01T00:00:00"
    db = root / "state.db"
    write_offline_snapshot(state, db)
    return root, db


def session(db):
    return RevisionedAuditSession(GuardedSQLiteStateStore(db))


def planning(db, signals):
    plan = plan_guarded_moves(preview_collection(
        database=db, now=NOW, thresholds=LIMITS, signals_by_key={KEY: signals}))
    return {"plan": plan, "now": NOW, "thresholds": LIMITS,
            "signals_by_key": {KEY: signals}}


def attempt(root, db, bundle, **kwargs):
    return execute_disposable_lifecycle_move(
        root=root, database=db, operation_id="op-1", media_key=KEY,
        observed_at=NOW, expected_revision=bundle["plan"]["source_revision"],
        planned_move=bundle, **kwargs)


def assert_unchanged(root, db, revision):
    latest = session(db)
    assert latest.revision == revision
    assert INTENTS_KEY not in latest.state
    assert (root / "transient" / "Movie").is_dir()
    assert not (root / "holding" / "Movie").exists()


def test_matching_advisory_plan_can_rehearse_move(tmp_path):
    root, db = lab(tmp_path)
    bundle = planning(db, {})
    assert attempt(root, db, bundle)["status"] == "disposable_reconciled"
    assert KEY in session(db).state["queued"]


def test_changed_jellyfin_decision_blocks_before_intent(tmp_path):
    root, db = lab(tmp_path)
    bundle = planning(db, {})
    revision = session(db).revision
    bundle["signals_by_key"] = {KEY: {"keep": True}}
    with pytest.raises(RuntimeError, match="plan changed"):
        attempt(root, db, bundle)
    assert_unchanged(root, db, revision)


def test_mismatched_destination_blocks_before_intent(tmp_path):
    root, db = lab(tmp_path)
    bundle = planning(db, {})
    revision = session(db).revision
    with pytest.raises(RuntimeError, match="does not match"):
        attempt(root, db, bundle, destination_stage="keep")
    assert_unchanged(root, db, revision)


def test_stale_sqlite_revision_blocks_before_intent(tmp_path):
    root, db = lab(tmp_path)
    bundle = planning(db, {})
    writer = session(db)
    writer.state["extra"] = {"change": True}
    writer.checkpoint()
    revision = session(db).revision
    with pytest.raises(RuntimeError, match="Stale disposable plan revision"):
        attempt(root, db, bundle)
    assert_unchanged(root, db, revision)


def test_missing_jellyfin_data_blocks(tmp_path):
    root, db = lab(tmp_path)
    bundle = planning(db, {})
    revision = session(db).revision
    bundle["signals_by_key"] = {}
    with pytest.raises(RuntimeError, match="plan changed"):
        attempt(root, db, bundle)
    assert_unchanged(root, db, revision)
