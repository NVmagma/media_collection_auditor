"""Crash windows around intent and applied checkpoints stay fail-closed."""

import pytest

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_operation_coordinator import INTENTS_KEY, SQLiteOperationCoordinator
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore


class FailAfterWrite:
    """Simulate losing acknowledgement after a durable SQLite commit."""

    def __init__(self, backing):
        self.backing = backing
        self.writes = 0
        self.fail_on = 1

    def load_with_revision(self):
        return self.backing.load_with_revision()

    def save_if_revision(self, state, revision):
        self.writes += 1
        self.backing.save_if_revision(state, revision)
        if self.writes == self.fail_on:
            raise OSError("acknowledgement lost")


def _setup(tmp_path):
    database = tmp_path / "state.db"
    write_offline_snapshot({section: {} for section in SECTIONS}, database)
    return GuardedSQLiteStateStore(database)


def test_begin_acknowledgement_loss_preserves_intent_and_blocks_replay(tmp_path):
    backing = _setup(tmp_path)
    faulty = FailAfterWrite(backing)
    session = RevisionedAuditSession(faulty)
    coordinator = SQLiteOperationCoordinator(session)
    with pytest.raises(OSError, match="acknowledgement lost"):
        coordinator.begin("move-1", "move", {
            "source": "/media/Waiting/Movie", "destination": "/media/Keep/Movie",
        })
    with pytest.raises(RuntimeError, match="reopen required"):
        coordinator.mark_applied("move-1")
    fresh = RevisionedAuditSession(backing)
    assert fresh.state[INTENTS_KEY]["phase"] == "intent_recorded"
    with pytest.raises(RuntimeError, match="Unresolved"):
        SQLiteOperationCoordinator(fresh).begin("move-2", "move", {"title": "Other"})


def test_applied_acknowledgement_loss_preserves_pending_reconciliation(tmp_path):
    backing = _setup(tmp_path)
    faulty = FailAfterWrite(backing)
    faulty.fail_on = 2
    session = RevisionedAuditSession(faulty)
    coordinator = SQLiteOperationCoordinator(session)
    coordinator.begin("arr-1", "arr_sync", {"title": "Movie"})
    with pytest.raises(OSError, match="acknowledgement lost"):
        coordinator.mark_applied("arr-1")
    with pytest.raises(RuntimeError, match="reopen required"):
        coordinator.mark_applied("arr-1")
    fresh = RevisionedAuditSession(backing)
    assert fresh.state[INTENTS_KEY]["phase"] == "applied_pending_reconciliation"
    with pytest.raises(RuntimeError, match="Unresolved"):
        SQLiteOperationCoordinator(fresh).begin("arr-2", "arr_sync", {"title": "Other"})
    with pytest.raises(RuntimeError, match="blocked pending trusted verification"):
        SQLiteOperationCoordinator(fresh).reconcile("arr-1", fresh.state)


@pytest.mark.parametrize("kind,details", [
    ("move", {"source": "/disposable/source", "destination": "/disposable/dest"}),
    ("arr_sync", {"title": "Disposable"}),
])
def test_crash_before_intent_checkpoint_leaves_no_pending_operation(
    tmp_path, kind, details,
):
    """No external action is attempted when the intent write fails first."""
    backing = _setup(tmp_path)

    class FailBeforeWrite:
        def load_with_revision(self):
            return backing.load_with_revision()

        def save_if_revision(self, state, revision):
            raise OSError("commit rejected before write")

    coordinator = SQLiteOperationCoordinator(RevisionedAuditSession(FailBeforeWrite()))
    with pytest.raises(OSError, match="commit rejected"):
        coordinator.begin("disposable-1", kind, details)
    fresh = RevisionedAuditSession(backing)
    assert INTENTS_KEY not in fresh.state


@pytest.mark.parametrize("kind,details", [
    ("move", {"source": "/disposable/source", "destination": "/disposable/dest"}),
    ("arr_sync", {"title": "Disposable"}),
])
def test_restart_after_intent_before_action_blocks_second_operation(
    tmp_path, kind, details,
):
    backing = _setup(tmp_path)
    SQLiteOperationCoordinator(RevisionedAuditSession(backing)).begin(
        "disposable-1", kind, details,
    )
    reopened = RevisionedAuditSession(backing)
    assert reopened.state[INTENTS_KEY]["phase"] == "intent_recorded"
    with pytest.raises(RuntimeError, match="Unresolved"):
        SQLiteOperationCoordinator(reopened).begin(
            "disposable-2", kind, details,
        )
    with pytest.raises(RuntimeError, match="not been confirmed"):
        SQLiteOperationCoordinator(reopened).reconcile("disposable-1", reopened.state)


@pytest.mark.parametrize("kind,details", [
    ("move", {"source": "/disposable/source", "destination": "/disposable/dest"}),
    ("arr_sync", {"title": "Disposable"}),
])
def test_restart_after_applied_checkpoint_refuses_reconciliation(
    tmp_path, kind, details,
):
    backing = _setup(tmp_path)
    coordinator = SQLiteOperationCoordinator(RevisionedAuditSession(backing))
    coordinator.begin("disposable-1", kind, details)
    coordinator.mark_applied("disposable-1")
    reopened = RevisionedAuditSession(backing)
    assert reopened.state[INTENTS_KEY]["phase"] == "applied_pending_reconciliation"
    with pytest.raises(RuntimeError, match="blocked pending trusted verification"):
        SQLiteOperationCoordinator(reopened).reconcile("disposable-1", reopened.state)
    assert RevisionedAuditSession(backing).state[INTENTS_KEY]["phase"] == (
        "applied_pending_reconciliation"
    )
