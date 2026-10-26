"""Read-only recovery inspection of durable SQLite intents."""

from pathlib import Path

import pytest

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_operation_coordinator import SQLiteOperationCoordinator
from app.sqlite_persisted_recovery_review import review_persisted_move
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore

STAGES = ("transient", "holding", "removal", "keep")


def _fixture(tmp_path, begin=True):
    paths = {}
    for stage in STAGES:
        root = tmp_path / stage
        root.mkdir()
        paths[stage] = str(root / "Movie")
    Path(paths["transient"]).mkdir()
    database = tmp_path / "state.db"
    state = {section: {} for section in SECTIONS}
    state["first_seen"]["DISPOSABLE/Movie"] = "2024-01-01T00:00:00"
    write_offline_snapshot(state, database)
    store = GuardedSQLiteStateStore(database)
    session = RevisionedAuditSession(store)
    if begin:
        SQLiteOperationCoordinator(session).begin_move_with_evidence(
            "operation-1", {
                "media_key": "DISPOSABLE/Movie",
                "source": paths["transient"], "destination": paths["holding"],
            }
        )
    return database, paths, session


def _review(session, paths, **overrides):
    args = {
        "operation_id": "operation-1",
        "media_key": "DISPOSABLE/Movie",
        "stage_paths": paths,
        "source_stage": "transient",
        "destination_stage": "holding",
    }
    args.update(overrides)
    return review_persisted_move(session, **args)


def _safe(result):
    assert result["authorization"] == "not_authorized"
    assert result["checkpoint_allowed"] is False
    assert result["intent_clearance"] == "blocked"
    assert result["replay_allowed"] is False


def test_fresh_session_reads_persisted_intent_without_writes(tmp_path):
    database, paths, _ = _fixture(tmp_path)
    Path(paths["transient"]).rename(paths["holding"])
    before = database.read_bytes()
    restarted = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    first = _review(restarted, paths)
    second = _review(restarted, paths)
    _safe(first)
    assert first == second
    assert first["status"] == "advisory"
    assert database.read_bytes() == before


def test_missing_persisted_intent_blocks(tmp_path):
    _, paths, session = _fixture(tmp_path, begin=False)
    result = _review(session, paths)
    _safe(result)
    assert result["reason"] == "persisted_intent_missing"


@pytest.mark.parametrize("overrides", [
    {"operation_id": "forged-operation"},
    {"media_key": "DISPOSABLE/Other"},
    {"destination_stage": "keep"},
])
def test_caller_identity_cannot_override_persisted_intent(tmp_path, overrides):
    _, paths, session = _fixture(tmp_path)
    result = _review(session, paths, **overrides)
    _safe(result)
    assert result["status"] == "blocked"


def test_stale_session_blocks_even_when_intent_was_valid(tmp_path):
    database, paths, session = _fixture(tmp_path)
    other = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    other.state["keep_seen"]["DISPOSABLE/Other"] = "2024-01-02T00:00:00"
    other.checkpoint()
    result = _review(session, paths)
    _safe(result)
    assert result["reason"] == "sqlite_session_unverified"


def test_uncheckpointed_session_mutation_is_rejected(tmp_path):
    _, paths, session = _fixture(tmp_path)
    session.state["queued"]["DISPOSABLE/Other"] = "2024-01-02T00:00:00"
    result = _review(session, paths)
    _safe(result)
    assert result["reason"] == "sqlite_session_unverified"


def test_missing_database_does_not_get_recreated(tmp_path):
    database, paths, session = _fixture(tmp_path)
    database.unlink()
    result = _review(session, paths)
    _safe(result)
    assert result["reason"] == "sqlite_session_unverified"
    assert not database.exists()
