"""Pre-commit SQLite failures must never trigger external operation replay."""

import pytest

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_operation_coordinator import INTENTS_KEY, SQLiteOperationCoordinator
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore


class FailBeforeWrite:
    def __init__(self, backing, fail_on):
        self.backing = backing
        self.fail_on = fail_on
        self.calls = 0

    def load_with_revision(self):
        return self.backing.load_with_revision()

    def save_if_revision(self, state, revision):
        self.calls += 1
        if self.calls == self.fail_on:
            raise OSError("precommit failure")
        return self.backing.save_if_revision(state, revision)


def _store(tmp_path):
    database = tmp_path / "audit.db"
    write_offline_snapshot({section: {} for section in SECTIONS}, database)
    return GuardedSQLiteStateStore(database)


def test_failed_begin_does_not_persist_intent_or_allow_same_session_retry(tmp_path):
    backing = _store(tmp_path)
    faulty = FailBeforeWrite(backing, fail_on=1)
    coordinator = SQLiteOperationCoordinator(RevisionedAuditSession(faulty))
    with pytest.raises(OSError, match="precommit failure"):
        coordinator.begin("move-1", "move", {"source": "/media/Waiting/Movie"})
    assert INTENTS_KEY not in RevisionedAuditSession(backing).state
    with pytest.raises(RuntimeError, match="reopen required"):
        coordinator.begin("move-1", "move", {"source": "/media/Waiting/Movie"})
    assert faulty.calls == 1


def test_failed_mark_applied_keeps_intent_unconfirmed(tmp_path):
    backing = _store(tmp_path)
    faulty = FailBeforeWrite(backing, fail_on=2)
    coordinator = SQLiteOperationCoordinator(RevisionedAuditSession(faulty))
    coordinator.begin("sync-1", "arr_sync", {"title": "Movie"})
    with pytest.raises(OSError, match="precommit failure"):
        coordinator.mark_applied("sync-1")
    assert RevisionedAuditSession(backing).state[INTENTS_KEY]["phase"] == "intent_recorded"
    with pytest.raises(RuntimeError, match="reopen required"):
        coordinator.mark_applied("sync-1")
    assert faulty.calls == 2


def test_stale_session_cannot_start_or_confirm_operations(tmp_path):
    backing = _store(tmp_path)
    stale = RevisionedAuditSession(backing)
    other = RevisionedAuditSession(backing)
    other.state["note"] = "newer"
    other.checkpoint()
    coordinator = SQLiteOperationCoordinator(stale)
    with pytest.raises(RuntimeError, match="stale"):
        coordinator.begin("move-1", "move", {"source": "/media/Waiting/Movie"})
    assert INTENTS_KEY not in RevisionedAuditSession(backing).state


def test_uncommitted_local_mutation_blocks_new_operation(tmp_path):
    backing = _store(tmp_path)
    session = RevisionedAuditSession(backing)
    session.state["note"] = "unsaved"
    with pytest.raises(RuntimeError, match="stale"):
        SQLiteOperationCoordinator(session).begin(
            "move-1", "move", {"source": "/media/Waiting/Movie"}
        )
    assert INTENTS_KEY not in RevisionedAuditSession(backing).state
