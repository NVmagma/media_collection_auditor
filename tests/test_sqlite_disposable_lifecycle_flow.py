"""End-to-end disposable SQLite lifecycle integration tests."""

from datetime import datetime

import pytest

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_disposable_lifecycle_flow import execute_disposable_lifecycle_move
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore

KEY = "DISPOSABLE/Movie"


def setup_lab(tmp_path):
    root = tmp_path / "lab"
    root.mkdir()
    (root / ".sqlite_disposable_rehearsal").write_text("DISPOSABLE ONLY\n")
    for stage in ("transient", "holding", "removal", "keep"):
        (root / stage).mkdir()
    source = root / "transient" / "Movie"
    source.mkdir()
    (source / "payload").write_text("disposable")
    database = root / "state.db"
    state = {section: {} for section in SECTIONS}
    state["first_seen"][KEY] = "2024-01-01T00:00:00"
    state["arr_sync_pending"]["other"] = {"attempts": 1, "last_error": "offline"}
    # Avoid relying on a particular Arr retry schema in this test.
    state["arr_sync_pending"].clear()
    state["custom_tracking"] = {"preserved": True}
    write_offline_snapshot(state, database)
    return root, database


def state_at(database):
    return RevisionedAuditSession(GuardedSQLiteStateStore(database)).state


def run(root, database, **kwargs):
    return execute_disposable_lifecycle_move(
        root=root, database=database, operation_id="op-1",
        media_key=KEY, observed_at=datetime(2024, 2, 1), **kwargs)


def test_complete_disposable_move_commits_one_lifecycle_change(tmp_path):
    root, database = setup_lab(tmp_path)
    before_revision = RevisionedAuditSession(GuardedSQLiteStateStore(database)).revision
    result = run(root, database)
    state = state_at(database)
    assert result["status"] == "disposable_reconciled"
    assert result["production_activation"] == "disabled"
    assert INTENTS_KEY not in state
    assert KEY not in state["first_seen"]
    assert state["queued"][KEY] == "2024-02-01T00:00:00"
    assert state["custom_tracking"] == {"preserved": True}
    assert (root / "holding" / "Movie" / "payload").read_text() == "disposable"
    after_revision = RevisionedAuditSession(GuardedSQLiteStateStore(database)).revision
    assert after_revision == before_revision + 3


@pytest.mark.parametrize("fault,phase,stage", [
    ("after_intent", "intent_recorded", "transient"),
    ("after_rename", "intent_recorded", "holding"),
    ("after_applied", "applied_pending_reconciliation", "holding"),
])
def test_crashes_leave_durable_unresolved_intent(tmp_path, fault, phase, stage):
    root, database = setup_lab(tmp_path)
    with pytest.raises(RuntimeError, match="Injected crash"):
        run(root, database, fault_at=fault)
    assert (root / stage / "Movie" / "payload").read_text() == "disposable"
    assert state_at(database)[INTENTS_KEY]["phase"] == phase
    assert KEY in state_at(database)["first_seen"]
    with pytest.raises(RuntimeError):
        run(root, database)
    assert state_at(database)[INTENTS_KEY]["phase"] == phase


def test_ambiguous_destination_blocks_before_intent(tmp_path):
    root, database = setup_lab(tmp_path)
    (root / "holding" / "Movie").mkdir()
    with pytest.raises(RuntimeError, match="Ambiguous"):
        run(root, database)
    assert INTENTS_KEY not in state_at(database)
    assert (root / "transient" / "Movie").exists()


def test_missing_disposable_marker_blocks_before_intent(tmp_path):
    root, database = setup_lab(tmp_path)
    (root / ".sqlite_disposable_rehearsal").unlink()
    with pytest.raises(RuntimeError, match="marker"):
        run(root, database)
    assert INTENTS_KEY not in state_at(database)
