"""Disposable stage-parent identity checks across filesystem moves."""

from datetime import datetime
import os

import pytest

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_disposable_lifecycle_flow import execute_disposable_lifecycle_move
from app.sqlite_disposable_parent_witness import pinned_stage_directories, assert_stage_directories_unchanged
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore


def lab(tmp_path):
    root = tmp_path / "lab"
    root.mkdir()
    (root / ".sqlite_disposable_rehearsal").write_text("DISPOSABLE ONLY\n")
    for stage in ("transient", "holding", "removal", "keep"):
        (root / stage).mkdir()
    (root / "transient" / "Movie").mkdir()
    state = {section: {} for section in SECTIONS}
    state["first_seen"]["DISPOSABLE/Movie"] = "2024-01-01T00:00:00"
    db = root / "state.db"
    write_offline_snapshot(state, db)
    return root, db


def test_pinned_stage_replacement_is_detected(tmp_path):
    root, _ = lab(tmp_path)
    with pinned_stage_directories(root, ("holding",)) as handles:
        (root / "holding").rename(root / "old_holding")
        (root / "holding").mkdir()
        with pytest.raises(RuntimeError, match="changed"):
            assert_stage_directories_unchanged(root, handles)


def test_parent_replaced_during_move_leaves_intent_unresolved(tmp_path, monkeypatch):
    root, db = lab(tmp_path)
    import app.sqlite_disposable_lifecycle_flow as flow
    actual = flow.rename_directory_noreplace

    def replace_parent_after_rename(source, destination):
        actual(source, destination)
        (root / "holding").rename(root / "old_holding")
        (root / "holding").mkdir()

    monkeypatch.setattr(flow, "rename_directory_noreplace", replace_parent_after_rename)
    with pytest.raises(RuntimeError, match="changed"):
        execute_disposable_lifecycle_move(
            root=root, database=db, operation_id="op-1",
            media_key="DISPOSABLE/Movie", observed_at=datetime(2024, 2, 1))
    persisted = RevisionedAuditSession(GuardedSQLiteStateStore(db)).state
    assert INTENTS_KEY in persisted
    assert "DISPOSABLE/Movie" in persisted["first_seen"]
    assert (root / "old_holding" / "Movie").is_dir()


def test_stable_parents_allow_complete_disposable_move(tmp_path):
    root, db = lab(tmp_path)
    result = execute_disposable_lifecycle_move(
        root=root, database=db, operation_id="op-1",
        media_key="DISPOSABLE/Movie", observed_at=datetime(2024, 2, 1))
    assert result["status"] == "disposable_reconciled"
    persisted = RevisionedAuditSession(GuardedSQLiteStateStore(db)).state
    assert INTENTS_KEY not in persisted
    assert "DISPOSABLE/Movie" in persisted["queued"]
