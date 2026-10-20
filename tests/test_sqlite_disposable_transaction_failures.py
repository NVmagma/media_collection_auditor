"""Inject failures around the final SQLite reconciliation transaction.

All paths are disposable. The two outcomes are deliberately different:
before-commit failure retains intent; after-commit uncertainty requires a
fresh read rather than guessing whether the transaction succeeded.
"""

from datetime import datetime

import pytest

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_disposable_lifecycle_flow import execute_disposable_lifecycle_move
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore

KEY = "DISPOSABLE/Movie"


def lab(tmp_path):
    root = tmp_path / "lab"
    root.mkdir()
    (root / ".sqlite_disposable_rehearsal").write_text("DISPOSABLE ONLY\n")
    for stage in ("transient", "holding", "removal", "keep"):
        (root / stage).mkdir()
    (root / "transient" / "Movie").mkdir()
    state = {section: {} for section in SECTIONS}
    state["first_seen"][KEY] = "2024-01-01T00:00:00"
    state["unrelated"] = {"keep": "untouched"}
    db = root / "state.db"
    write_offline_snapshot(state, db)
    return root, db


def state_at(db):
    return RevisionedAuditSession(GuardedSQLiteStateStore(db)).state


def execute(root, db):
    return execute_disposable_lifecycle_move(
        root=root, database=db, operation_id="op-1", media_key=KEY,
        observed_at=datetime(2024, 2, 1))


def test_failure_before_final_commit_preserves_intent_and_original_clock(tmp_path, monkeypatch):
    root, db = lab(tmp_path)
    original = RevisionedAuditSession.checkpoint
    calls = 0

    def fail_third_checkpoint(self):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("Injected failure before final transaction")
        return original(self)

    monkeypatch.setattr(RevisionedAuditSession, "checkpoint", fail_third_checkpoint)
    with pytest.raises(RuntimeError, match="Injected failure"):
        execute(root, db)
    assert calls == 3
    state = state_at(db)
    assert state[INTENTS_KEY]["phase"] == "applied_pending_reconciliation"
    assert KEY in state["first_seen"]
    assert KEY not in state["queued"]
    assert state["unrelated"] == {"keep": "untouched"}
    assert (root / "holding" / "Movie").is_dir()
    with pytest.raises(RuntimeError):
        execute(root, db)


def test_exception_after_commit_requires_fresh_read_not_replay(tmp_path, monkeypatch):
    root, db = lab(tmp_path)
    original = RevisionedAuditSession.checkpoint
    calls = 0

    def fail_after_third_checkpoint(self):
        nonlocal calls
        calls += 1
        result = original(self)
        if calls == 3:
            raise RuntimeError("Injected uncertainty after final commit")
        return result

    monkeypatch.setattr(RevisionedAuditSession, "checkpoint", fail_after_third_checkpoint)
    with pytest.raises(RuntimeError, match="Injected uncertainty"):
        execute(root, db)
    assert calls == 3
    state = state_at(db)
    assert INTENTS_KEY not in state
    assert KEY not in state["first_seen"]
    assert state["queued"][KEY] == "2024-02-01T00:00:00"
    assert state["unrelated"] == {"keep": "untouched"}
    assert (root / "holding" / "Movie").is_dir()
    with pytest.raises(RuntimeError):
        execute(root, db)
