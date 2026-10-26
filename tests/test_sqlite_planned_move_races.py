"""Disposable-only adversarial checks at plan-to-intent and crash boundaries."""

from datetime import datetime

import pytest

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_collection_decision_preview import preview_collection
from app.sqlite_disposable_lifecycle_flow import execute_disposable_lifecycle_move
from app.sqlite_guarded_move_plan import plan_guarded_moves
from app.sqlite_operation_coordinator import INTENTS_KEY, SQLiteOperationCoordinator
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore

KEY = "DISPOSABLE/Movie"
NOW = datetime(2024, 2, 1)
LIMITS = {"Waiting": 7, "Holding": 7, "Removal": 7, "Keep": 0}


def setup(tmp_path):
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
    return execute_disposable_lifecycle_move(
        root=root, database=db, operation_id="op-1", media_key=KEY,
        observed_at=NOW, expected_revision=bundle["plan"]["source_revision"],
        planned_move=bundle, **kwargs)


def state(db):
    session = RevisionedAuditSession(GuardedSQLiteStateStore(db))
    return session.state, session.revision


def test_concurrent_writer_after_review_blocks_intent_and_rename(tmp_path, monkeypatch):
    root, db, bundle = setup(tmp_path)
    original = SQLiteOperationCoordinator.begin_move_with_evidence

    def race(self, operation_id, details):
        writer = RevisionedAuditSession(GuardedSQLiteStateStore(db))
        writer.state["concurrent_change"] = {"persisted": True}
        writer.checkpoint()
        return original(self, operation_id, details)

    monkeypatch.setattr(SQLiteOperationCoordinator, "begin_move_with_evidence", race)
    with pytest.raises(RuntimeError, match="stale"):
        run(root, db, bundle)
    persisted, revision = state(db)
    assert revision == bundle["plan"]["source_revision"] + 1
    assert INTENTS_KEY not in persisted
    assert persisted["concurrent_change"] == {"persisted": True}
    assert (root / "transient" / "Movie").is_dir()
    assert not (root / "holding" / "Movie").exists()


@pytest.mark.parametrize("fault,stage,phase", [
    ("after_intent", "transient", "intent_recorded"),
    ("after_rename", "holding", "intent_recorded"),
    ("after_applied", "holding", "applied_pending_reconciliation"),
])
def test_plan_bound_crashes_remain_pending(tmp_path, fault, stage, phase):
    root, db, bundle = setup(tmp_path)
    with pytest.raises(RuntimeError, match="Injected crash"):
        run(root, db, bundle, fault_at=fault)
    persisted, _ = state(db)
    assert persisted[INTENTS_KEY]["phase"] == phase
    assert KEY in persisted["first_seen"]
    assert KEY not in persisted["queued"]
    assert (root / stage / "Movie").is_dir()
    with pytest.raises(RuntimeError):
        run(root, db, bundle)


def test_plan_bound_success_is_atomic_and_clears_intent(tmp_path):
    root, db, bundle = setup(tmp_path)
    before = bundle["plan"]["source_revision"]
    assert run(root, db, bundle)["status"] == "disposable_reconciled"
    persisted, revision = state(db)
    assert revision == before + 3
    assert INTENTS_KEY not in persisted
    assert KEY not in persisted["first_seen"]
    assert persisted["queued"][KEY] == NOW.isoformat()
