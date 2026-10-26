"""Read-only SQLite recovery checks reject stale and changing state."""

import pytest

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_session_recovery import inspect_session_recovery
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore


def _setup(tmp_path):
    database = tmp_path / "audit.db"
    state = {section: {} for section in SECTIONS}
    state[INTENTS_KEY] = {
        "id": "arr-1", "kind": "arr_sync",
        "phase": "applied_pending_reconciliation",
        "details": {
            "service": "radarr", "title_id": 7,
            "root": "/media/Movies_keep", "monitored": True,
        },
    }
    write_offline_snapshot(state, database)
    return GuardedSQLiteStateStore(database)


def _inspect(session):
    return inspect_session_recovery(
        session,
        jellyfin_evidence={
            "available": True, "complete": True, "keep": False,
            "keep_forever": False, "keep_all_seasons": False,
            "favorite": False,
        },
        arr_record={"id": 7, "path": "/media/Movies_keep/Movie", "monitored": True},
    )


def test_current_revision_diagnostic_does_not_clear_intent(tmp_path):
    store = _setup(tmp_path)
    session = RevisionedAuditSession(store)
    report = _inspect(session)
    assert report["state_revision"] == 0
    assert report["authorization"] == "blocked_pending_independent_verification"
    assert INTENTS_KEY in RevisionedAuditSession(store).state


def test_concurrent_checkpoint_invalidates_stale_session(tmp_path):
    store = _setup(tmp_path)
    stale = RevisionedAuditSession(store)
    other = RevisionedAuditSession(store)
    other.state["audit_note"] = "new"
    other.checkpoint()
    with pytest.raises(RuntimeError, match="stale"):
        _inspect(stale)


def test_uncheckpointed_local_changes_are_not_trusted(tmp_path):
    store = _setup(tmp_path)
    session = RevisionedAuditSession(store)
    session.state["audit_note"] = "not persisted"
    with pytest.raises(RuntimeError, match="stale"):
        _inspect(session)


def test_revision_change_during_inspection_is_rejected(tmp_path, monkeypatch):
    store = _setup(tmp_path)
    session = RevisionedAuditSession(store)
    original = session.read_verified_snapshot
    calls = 0

    def race():
        nonlocal calls
        calls += 1
        if calls == 2:
            other = RevisionedAuditSession(store)
            other.state["audit_note"] = "raced"
            other.checkpoint()
        return original()

    monkeypatch.setattr(session, "read_verified_snapshot", race)
    with pytest.raises(RuntimeError, match="stale"):
        _inspect(session)
