"""Disposable reconciliation candidate tests; no candidate is committed."""

from datetime import datetime
from pathlib import Path

import pytest

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_operation_coordinator import INTENTS_KEY, SQLiteOperationCoordinator
from app.sqlite_reconciliation_candidate import plan_atomic_move_reconciliation
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore

STAGES = ("transient", "holding", "removal", "keep")
KEY = "DISPOSABLE/Movie"


def _fixture(tmp_path, move=True):
    paths = {}
    for stage in STAGES:
        root = tmp_path / stage
        root.mkdir()
        paths[stage] = str(root / "Movie")
    Path(paths["transient"]).mkdir()
    database = tmp_path / "state.db"
    state = {section: {} for section in SECTIONS}
    state["first_seen"][KEY] = "2024-01-01T00:00:00"
    write_offline_snapshot(state, database)
    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    SQLiteOperationCoordinator(session).begin_move_with_evidence(
        "op-1", {"media_key": KEY, "source": paths["transient"],
                 "destination": paths["holding"]})
    if move:
        Path(paths["transient"]).rename(paths["holding"])
    return database, paths


def _plan(database, paths, **overrides):
    args = dict(
        operation_id="op-1", media_key=KEY, stage_paths=paths,
        source_stage="transient", destination_stage="holding",
        observed_at=datetime(2024, 2, 1),
    )
    args.update(overrides)
    return plan_atomic_move_reconciliation(
        RevisionedAuditSession(GuardedSQLiteStateStore(database)), **args)


def _blocked(result):
    assert result["authorization"] == "not_authorized"
    assert result["checkpoint_allowed"] is False
    assert result["intent_clearance"] == "blocked"
    assert result["replay_allowed"] is False
    assert result["production_activation"] == "disabled"


def test_one_detached_candidate_changes_clock_and_intent_together(tmp_path):
    database, paths = _fixture(tmp_path)
    before = database.read_bytes()
    original = RevisionedAuditSession(GuardedSQLiteStateStore(database)).state
    result = _plan(database, paths)
    _blocked(result)
    assert result["status"] == "advisory"
    candidate = result["candidate_state"]
    assert KEY not in candidate["first_seen"]
    assert candidate["queued"][KEY] == "2024-02-01T00:00:00"
    assert INTENTS_KEY not in candidate
    assert original["first_seen"][KEY] == "2024-01-01T00:00:00"
    assert INTENTS_KEY in original
    assert database.read_bytes() == before


@pytest.mark.parametrize("change", [
    {"operation_id": "wrong"},
    {"media_key": "DISPOSABLE/Other"},
    {"destination_stage": "keep"},
    {"observed_at": datetime(2099, 1, 1)},
])
def test_mismatches_do_not_produce_candidate(tmp_path, change):
    database, paths = _fixture(tmp_path)
    result = _plan(database, paths, **change)
    _blocked(result)
    assert result["status"] == "blocked"
    assert "candidate_state" not in result


def test_unmoved_source_blocks_candidate(tmp_path):
    database, paths = _fixture(tmp_path, move=False)
    result = _plan(database, paths)
    _blocked(result)
    assert result["status"] == "blocked"
    assert "candidate_state" not in result


def test_conflicting_clock_blocks_candidate(tmp_path):
    database, paths = _fixture(tmp_path)
    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    session.state["queued"][KEY] = "2024-01-02T00:00:00"
    session.checkpoint()
    result = _plan(database, paths)
    _blocked(result)
    assert result["reason"] == "conflicting_lifecycle_clocks"
