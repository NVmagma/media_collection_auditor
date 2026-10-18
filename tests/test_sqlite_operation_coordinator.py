"""Crash-safe intent tracking tests; no media operations are executed."""

import pytest

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_operation_coordinator import (
    INTENTS_KEY, SQLiteOperationCoordinator,
)
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore


def _session(tmp_path):
    database = tmp_path / "state.db"
    write_offline_snapshot({section: {} for section in SECTIONS}, database)
    return database, RevisionedAuditSession(GuardedSQLiteStateStore(database))


def _reopen(database):
    return RevisionedAuditSession(GuardedSQLiteStateStore(database))


def test_intent_survives_restart_and_blocks_new_operation(tmp_path):
    database, session = _session(tmp_path)
    coordinator = SQLiteOperationCoordinator(session)
    coordinator.begin("move-1", "move", {"source": "/media/Waiting/Movie"})
    restarted = _reopen(database)
    assert restarted.state[INTENTS_KEY]["phase"] == "intent_recorded"
    with pytest.raises(RuntimeError, match="Unresolved"):
        SQLiteOperationCoordinator(restarted).begin(
            "move-2", "move", {"source": "/media/Waiting/Other"}
        )


def test_applied_phase_requires_explicit_reconciliation(tmp_path):
    database, session = _session(tmp_path)
    coordinator = SQLiteOperationCoordinator(session)
    coordinator.begin("sync-1", "arr_sync", {"title": "Movie"})
    coordinator.mark_applied("sync-1")
    restarted = _reopen(database)
    assert restarted.state[INTENTS_KEY]["phase"] == "applied_pending_reconciliation"
    with pytest.raises(RuntimeError, match="blocked pending trusted verification"):
        SQLiteOperationCoordinator(restarted).reconcile("sync-1", restarted.state)
    with pytest.raises(RuntimeError, match="blocked pending trusted verification"):
        SQLiteOperationCoordinator(restarted).reconcile("sync-1", restarted.state | {
            INTENTS_KEY: {}
        })
    assert _reopen(database).state[INTENTS_KEY]["phase"] == "applied_pending_reconciliation"


def test_cannot_confirm_unrecorded_or_wrong_operation(tmp_path):
    _, session = _session(tmp_path)
    coordinator = SQLiteOperationCoordinator(session)
    with pytest.raises(RuntimeError, match="Missing"):
        coordinator.mark_applied("missing")
    coordinator.begin("move-1", "move", {"title": "Movie"})
    with pytest.raises(RuntimeError, match="mismatched"):
        coordinator.mark_applied("move-2")
    with pytest.raises(RuntimeError, match="not been confirmed"):
        coordinator.reconcile("move-1", session.state)


def test_invalid_intent_is_not_persisted(tmp_path):
    database, session = _session(tmp_path)
    coordinator = SQLiteOperationCoordinator(session)
    with pytest.raises(RuntimeError, match="Unsupported"):
        coordinator.begin("delete-1", "delete", {"title": "Movie"})
    with pytest.raises(RuntimeError, match="details"):
        coordinator.begin("move-1", "move", {})
    assert INTENTS_KEY not in _reopen(database).state
