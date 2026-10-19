"""Disposable SQLite restart and ambiguous-checkpoint safety rehearsals."""

import pytest

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore


def make_db(tmp_path):
    path = tmp_path / "state.db"
    write_offline_snapshot({section: {} for section in SECTIONS}, path)
    return path


def test_restarted_session_sees_committed_state_and_stale_worker_is_blocked(tmp_path):
    path = make_db(tmp_path)
    old = RevisionedAuditSession(GuardedSQLiteStateStore(path))
    writer = RevisionedAuditSession(GuardedSQLiteStateStore(path))
    writer.state["first_seen"]["Film"] = "2024-01-01T01:02:03"
    writer.checkpoint()
    reopened = RevisionedAuditSession(GuardedSQLiteStateStore(path))
    assert reopened.revision == 1
    assert reopened.state["first_seen"]["Film"] == "2024-01-01T01:02:03"
    with pytest.raises(RuntimeError, match="stale"):
        old.read_verified_snapshot()
    old.state["queued"]["Film"] = "2024-01-02T01:02:03"
    with pytest.raises(RuntimeError, match="Stale SQLite state revision"):
        old.checkpoint()
    with pytest.raises(RuntimeError, match="invalid after failed checkpoint"):
        old.checkpoint()
    assert RevisionedAuditSession(GuardedSQLiteStateStore(path)).state == reopened.state


def test_commit_then_transport_failure_quarantines_session(tmp_path):
    path = make_db(tmp_path)
    backend = GuardedSQLiteStateStore(path)

    class CommitThenFail:
        def load_with_revision(self):
            return backend.load_with_revision()

        def save_if_revision(self, state, revision):
            backend.save_if_revision(state, revision)
            raise OSError("simulated lost acknowledgment after durable commit")

    session = RevisionedAuditSession(CommitThenFail())
    session.state["keep_seen"]["Film"] = "2024-01-01T01:02:03"
    with pytest.raises(OSError, match="lost acknowledgment"):
        session.checkpoint()
    with pytest.raises(RuntimeError, match="invalid after failed checkpoint"):
        session.read_verified_snapshot()
    with pytest.raises(RuntimeError, match="invalid after failed checkpoint"):
        session.checkpoint()
    reopened = RevisionedAuditSession(GuardedSQLiteStateStore(path))
    assert reopened.revision == 1
    assert reopened.state["keep_seen"]["Film"] == "2024-01-01T01:02:03"


def test_failure_before_commit_preserves_original_revision(tmp_path):
    path = make_db(tmp_path)
    backend = GuardedSQLiteStateStore(path)

    class FailBeforeCommit:
        def load_with_revision(self):
            return backend.load_with_revision()

        def save_if_revision(self, state, revision):
            raise OSError("simulated disk failure before commit")

    session = RevisionedAuditSession(FailBeforeCommit())
    session.state["queued"]["Film"] = "2024-01-01T01:02:03"
    with pytest.raises(OSError, match="disk failure"):
        session.checkpoint()
    assert RevisionedAuditSession(GuardedSQLiteStateStore(path)).revision == 0
    assert RevisionedAuditSession(GuardedSQLiteStateStore(path)).state["queued"] == {}
