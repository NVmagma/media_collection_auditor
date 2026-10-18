"""Disposable full-lifecycle SQLite rehearsal; never touches real media."""

import json

import pytest

from app.sqlite_audit_bootstrap import open_isolated_sqlite_audit
from app.sqlite_migration import create_offline_migration_snapshot
from app.sqlite_operation_coordinator import INTENTS_KEY, SQLiteOperationCoordinator
from app.sqlite_readiness import inspect_sqlite_readiness
from app.sqlite_audit_session import RevisionedAuditSession
from app.state_store import GuardedSQLiteStateStore


def _setup(tmp_path):
    source = tmp_path / "state.json"
    backup = tmp_path / "state.backup.json"
    database = tmp_path / "state.db"
    state = {
        "first_seen": {"Film": "2024-01-01T01:02:03"},
        "queued": {}, "in_removal": {}, "keep_seen": {},
        "arr_sync_pending": {},
        "legacy": {"Film": {"history": ["waiting", "keep"]}},
    }
    original = json.dumps(state, indent=2).encode()
    source.write_bytes(original)
    create_offline_migration_snapshot(source, backup, database)
    return source, backup, database, original, state


def test_full_rehearsal_move_then_arr_sync_with_restart(tmp_path):
    source, backup, database, original, baseline = _setup(tmp_path)
    media = tmp_path / "disposable_media"
    waiting = media / "Waiting" / "Film"
    kept = media / "Keep" / "Film"
    waiting.mkdir(parents=True)
    (waiting / "test.txt").write_text("disposable fixture")
    assert inspect_sqlite_readiness(source, backup, database)["ready_for_isolated_review"]
    session = open_isolated_sqlite_audit(source, backup, database)
    coordinator = SQLiteOperationCoordinator(session)

    # The intent must be committed before the simulated filesystem move.
    coordinator.begin("move-1", "move", {
        "source": str(waiting), "destination": str(kept),
    })
    assert waiting.exists() and not kept.exists()
    kept.parent.mkdir(parents=True)
    waiting.rename(kept)
    assert (kept / "test.txt").read_text() == "disposable fixture"

    # Simulate process loss before acknowledgement; never replay the move.
    restarted = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    assert restarted.state[INTENTS_KEY]["phase"] == "intent_recorded"
    with pytest.raises(RuntimeError, match="SQLite snapshot differs from JSON backup"):
        open_isolated_sqlite_audit(source, backup, database)
    with pytest.raises(RuntimeError, match="Unresolved"):
        SQLiteOperationCoordinator(restarted).begin(
            "arr-1", "arr_sync", {"service": "radarr", "id": 1}
        )
    assert inspect_sqlite_readiness(source, backup, database)["ready_for_isolated_review"] is False
    assert (kept / "test.txt").exists()
    assert not waiting.exists()
    assert restarted.state["legacy"] == baseline["legacy"]
    assert source.read_bytes() == backup.read_bytes() == original

    # An independent caller confirms the fixture move, but this still
    # cannot clear the pending intent or authorize a new operation.
    SQLiteOperationCoordinator(restarted).mark_applied("move-1")
    again = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    assert again.state[INTENTS_KEY]["phase"] == "applied_pending_reconciliation"
    with pytest.raises(RuntimeError, match="trusted verification"):
        SQLiteOperationCoordinator(again).reconcile("move-1", again.state)
    with pytest.raises(RuntimeError, match="Unresolved"):
        SQLiteOperationCoordinator(again).begin(
            "arr-1", "arr_sync", {"service": "radarr", "id": 1}
        )
    assert again.state["first_seen"] == baseline["first_seen"]
    assert again.state["legacy"] == baseline["legacy"]


def test_rehearsal_arr_sync_crash_preserves_pending_and_tracking(tmp_path):
    source, backup, database, original, baseline = _setup(tmp_path)
    session = open_isolated_sqlite_audit(source, backup, database)
    coordinator = SQLiteOperationCoordinator(session)
    coordinator.begin("arr-1", "arr_sync", {
        "service": "sonarr", "title_id": 17, "monitored": True,
    })
    # No actual Arr API call. Model an externally successful sync.
    coordinator.mark_applied("arr-1")
    del coordinator, session
    reopened = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    assert reopened.state[INTENTS_KEY]["kind"] == "arr_sync"
    assert reopened.state[INTENTS_KEY]["phase"] == "applied_pending_reconciliation"
    with pytest.raises(RuntimeError, match="SQLite snapshot differs from JSON backup"):
        open_isolated_sqlite_audit(source, backup, database)
    assert reopened.state["legacy"] == baseline["legacy"]
    assert source.read_bytes() == backup.read_bytes() == original


def test_rehearsal_stale_session_cannot_overwrite_new_checkpoint(tmp_path):
    source, backup, database, original, baseline = _setup(tmp_path)
    first = open_isolated_sqlite_audit(source, backup, database)
    second = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    SQLiteOperationCoordinator(first).begin(
        "move-1", "move", {"source": "/disposable/source"}
    )
    with pytest.raises(RuntimeError, match="stale"):
        SQLiteOperationCoordinator(second).begin(
            "move-2", "move", {"source": "/disposable/other"}
        )
    persisted = RevisionedAuditSession(GuardedSQLiteStateStore(database)).state
    assert persisted[INTENTS_KEY]["id"] == "move-1"
    assert persisted["legacy"] == baseline["legacy"]
    assert source.read_bytes() == backup.read_bytes() == original
