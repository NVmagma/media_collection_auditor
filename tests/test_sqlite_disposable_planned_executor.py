from datetime import datetime

import pytest

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_collection_decision_preview import preview_collection
from app.sqlite_disposable_planned_executor import rehearse_planned_disposable_move
from app.sqlite_guarded_move_plan import plan_guarded_moves
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore

KEY = "DISPOSABLE/Movie"
NOW = datetime(2024, 2, 1)
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
    plan = plan_guarded_moves(preview_collection(
        database=db, now=NOW, thresholds=LIMITS, signals_by_key={KEY: {}}))
    bundle = {"plan": plan, "now": NOW, "thresholds": LIMITS,
              "signals_by_key": {KEY: {}}}
    return root, db, bundle


def run(root, db, bundle, **kwargs):
    return rehearse_planned_disposable_move(
        root=root, database=db, operation_id="op-1",
        media_key=KEY, planned_move=bundle, observed_at=NOW, **kwargs)


def assert_no_move(root, db):
    assert (root / "transient" / "Movie").is_dir()
    assert not (root / "holding" / "Movie").exists()
    assert INTENTS_KEY not in RevisionedAuditSession(
        GuardedSQLiteStateStore(db)).state


def test_strict_entry_point_rehearses_matching_candidate(tmp_path):
    root, db, bundle = lab(tmp_path)
    assert run(root, db, bundle)["status"] == "disposable_reconciled"
    state = RevisionedAuditSession(GuardedSQLiteStateStore(db)).state
    assert KEY in state["queued"]
    assert INTENTS_KEY not in state


@pytest.mark.parametrize("bundle", [None, {}, {"plan": {}}, {"plan": {"source_revision": True}}])
def test_missing_or_invalid_plan_fails_before_move(tmp_path, bundle):
    root, db, _ = lab(tmp_path)
    with pytest.raises(ValueError):
        run(root, db, bundle)
    assert_no_move(root, db)


def test_tampered_required_checks_fail_before_move(tmp_path):
    root, db, bundle = lab(tmp_path)
    bundle["plan"]["rows"][0]["required_checks"] = []
    with pytest.raises(RuntimeError, match="No matching"):
        run(root, db, bundle)
    assert_no_move(root, db)


def test_unplanned_destination_fails_before_move(tmp_path):
    root, db, bundle = lab(tmp_path)
    with pytest.raises(RuntimeError, match="No matching"):
        run(root, db, bundle, destination_stage="keep")
    assert_no_move(root, db)


def test_stale_revision_fails_before_move(tmp_path):
    root, db, bundle = lab(tmp_path)
    writer = RevisionedAuditSession(GuardedSQLiteStateStore(db))
    writer.state["other"] = {"changed": True}
    writer.checkpoint()
    with pytest.raises(RuntimeError, match="Stale disposable plan revision"):
        run(root, db, bundle)
    assert_no_move(root, db)


def test_missing_signals_fail_before_move(tmp_path):
    root, db, bundle = lab(tmp_path)
    bundle["signals_by_key"] = {}
    with pytest.raises(RuntimeError, match="plan changed"):
        run(root, db, bundle)
    assert_no_move(root, db)
