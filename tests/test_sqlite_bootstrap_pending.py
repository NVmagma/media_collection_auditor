"""Isolated bootstrap must not accept unresolved operation state."""

import pytest

from app import sqlite_audit_bootstrap
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore


def _store(tmp_path, pending=None):
    database = tmp_path / "audit.db"
    state = {section: {} for section in SECTIONS}
    if pending is not None:
        state[INTENTS_KEY] = pending
    write_offline_snapshot(state, database)
    store = GuardedSQLiteStateStore(database)
    baseline, revision = store.load_with_revision()
    return store, baseline, revision


@pytest.mark.parametrize("pending", [
    {"id": "move-1", "kind": "move", "phase": "intent_recorded",
     "details": {"source": "/media/Waiting/Movie"}},
    {"id": "sync-1", "kind": "arr_sync",
     "phase": "applied_pending_reconciliation",
     "details": {"service": "radarr"}},
    {},
])
def test_pending_operation_blocks_isolated_bootstrap(tmp_path, monkeypatch, pending):
    store, baseline, revision = _store(tmp_path, pending)
    monkeypatch.setattr(
        sqlite_audit_bootstrap, "prepare_sqlite_audit_state",
        lambda *args: (store, baseline, revision),
    )
    with pytest.raises(RuntimeError, match="unresolved operation"):
        sqlite_audit_bootstrap.open_isolated_sqlite_audit("source", "backup", "db")
    persisted, current_revision = store.load_with_revision()
    assert persisted == baseline
    assert current_revision == revision


def test_clean_snapshot_can_open_isolated_session(tmp_path, monkeypatch):
    store, baseline, revision = _store(tmp_path)
    monkeypatch.setattr(
        sqlite_audit_bootstrap, "prepare_sqlite_audit_state",
        lambda *args: (store, baseline, revision),
    )
    session = sqlite_audit_bootstrap.open_isolated_sqlite_audit(
        "source", "backup", "db"
    )
    assert session.state == baseline
    assert session.revision == revision


def test_stale_preflight_baseline_rejected(tmp_path, monkeypatch):
    store, baseline, revision = _store(tmp_path)
    monkeypatch.setattr(
        sqlite_audit_bootstrap, "prepare_sqlite_audit_state",
        lambda *args: (store, baseline | {"unsaved": True}, revision),
    )
    with pytest.raises(RuntimeError, match="changed during"):
        sqlite_audit_bootstrap.open_isolated_sqlite_audit("source", "backup", "db")
