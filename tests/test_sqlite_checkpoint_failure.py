"""A failed checkpoint must never be retried using the same session."""

import pytest

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore


class UncertainStore:
    def __init__(self, backing, *, committed):
        self.backing = backing
        self.committed = committed
        self.calls = 0

    def load_with_revision(self):
        return self.backing.load_with_revision()

    def save_if_revision(self, state, revision):
        self.calls += 1
        if self.committed:
            self.backing.save_if_revision(state, revision)
        raise OSError("simulated write failure")


@pytest.mark.parametrize("committed", [False, True])
def test_failed_checkpoint_quarantines_session(tmp_path, committed):
    database = tmp_path / "audit.db"
    write_offline_snapshot({section: {} for section in SECTIONS}, database)
    backing = GuardedSQLiteStateStore(database)
    store = UncertainStore(backing, committed=committed)
    session = RevisionedAuditSession(store)
    session.state["note"] = "pending"
    with pytest.raises(OSError, match="simulated"):
        session.checkpoint()
    with pytest.raises(RuntimeError, match="reopen required"):
        session.checkpoint()
    with pytest.raises(RuntimeError, match="reopen required"):
        session.read_verified_snapshot()
    assert store.calls == 1
    fresh = RevisionedAuditSession(backing)
    assert ("note" in fresh.state) is committed
    assert fresh.revision == int(committed)


def test_failed_readback_quarantines_session(tmp_path):
    database = tmp_path / "audit.db"
    write_offline_snapshot({section: {} for section in SECTIONS}, database)
    backing = GuardedSQLiteStateStore(database)

    class FailedReadback:
        def __init__(self):
            self.reads = 0

        def load_with_revision(self):
            self.reads += 1
            if self.reads > 1:
                raise OSError("readback unavailable")
            return backing.load_with_revision()

        def save_if_revision(self, state, revision):
            backing.save_if_revision(state, revision)

    session = RevisionedAuditSession(FailedReadback())
    session.state["note"] = "committed"
    with pytest.raises(OSError, match="readback"):
        session.checkpoint()
    with pytest.raises(RuntimeError, match="reopen required"):
        session.checkpoint()
    assert RevisionedAuditSession(backing).state["note"] == "committed"
