"""Audit checkpoint integration tests using disposable SQLite state."""

import pytest

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore


def _state():
    return {section: {} for section in SECTIONS}


def test_session_checkpoints_preserve_lifecycle_and_retry(tmp_path):
    path = tmp_path / "state.db"
    write_offline_snapshot(_state(), path)
    session = RevisionedAuditSession(GuardedSQLiteStateStore(path))
    session.state["first_seen"]["Movie"] = "2024-01-01T01:02:03"
    session.checkpoint()
    session.state["arr_sync_pending"]["Movie"] = {
        "stage": "keep", "root": "/media/Movies_keep", "monitored": False,
    }
    session.state["extra_history"] = {"legacy": ["preserved"]}
    session.checkpoint()
    reopened = RevisionedAuditSession(GuardedSQLiteStateStore(path))
    assert reopened.revision == 2
    assert reopened.state == session.state


def test_concurrent_audit_session_fails_without_erasing_changes(tmp_path):
    path = tmp_path / "state.db"
    write_offline_snapshot(_state(), path)
    first = RevisionedAuditSession(GuardedSQLiteStateStore(path))
    second = RevisionedAuditSession(GuardedSQLiteStateStore(path))
    first.state["queued"]["Movie"] = "2024-01-01T01:02:03"
    first.checkpoint()
    second.state["in_removal"]["Movie"] = "2024-01-02T01:02:03"
    with pytest.raises(RuntimeError, match="Stale SQLite state revision"):
        second.checkpoint()
    assert RevisionedAuditSession(GuardedSQLiteStateStore(path)).state == first.state
    assert second.revision == 0


def test_session_rejects_missing_database(tmp_path):
    with pytest.raises(RuntimeError, match="unavailable"):
        RevisionedAuditSession(GuardedSQLiteStateStore(tmp_path / "missing.db"))


def test_session_rejects_invalid_state_without_revision_change(tmp_path):
    path = tmp_path / "state.db"
    write_offline_snapshot(_state(), path)
    session = RevisionedAuditSession(GuardedSQLiteStateStore(path))
    session.state["first_seen"]["Movie"] = "2999-01-01T00:00:00"
    with pytest.raises(RuntimeError, match="timestamp"):
        session.checkpoint()
    reopened = RevisionedAuditSession(GuardedSQLiteStateStore(path))
    assert reopened.state == _state()
    assert reopened.revision == 0
