"""Guard planned revision at the durable-intent boundary."""

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
    state = {name: {} for name in SECTIONS}
    state["first_seen"][KEY] = "2024-01-01T00:00:00"
    db = root / "state.db"
    write_offline_snapshot(state, db)
    return root, db


def session(db):
    return RevisionedAuditSession(GuardedSQLiteStateStore(db))


def run(root, db, revision):
    return execute_disposable_lifecycle_move(
        root=root, database=db, operation_id="op-1", media_key=KEY,
        observed_at=datetime(2024, 2, 1), expected_revision=revision)


def test_current_revision_can_complete_disposable_move(tmp_path):
    root, db = lab(tmp_path)
    revision = session(db).revision
    assert run(root, db, revision)["status"] == "disposable_reconciled"
    assert KEY in session(db).state["queued"]


def test_changed_revision_blocks_before_intent_and_rename(tmp_path):
    root, db = lab(tmp_path)
    planned_revision = session(db).revision
    newer = session(db)
    newer.state["other_tracking"] = {"preserved": True}
    newer.checkpoint()
    with pytest.raises(RuntimeError, match="Stale disposable plan revision"):
        run(root, db, planned_revision)
    persisted = session(db)
    assert persisted.revision == planned_revision + 1
    assert INTENTS_KEY not in persisted.state
    assert KEY in persisted.state["first_seen"]
    assert (root / "transient" / "Movie").is_dir()
    assert not (root / "holding" / "Movie").exists()


@pytest.mark.parametrize("bad", [-1, True, "0"])
def test_invalid_expected_revision_blocks(tmp_path, bad):
    root, db = lab(tmp_path)
    with pytest.raises(ValueError, match="Invalid expected"):
        run(root, db, bad)
    assert INTENTS_KEY not in session(db).state
    assert (root / "transient" / "Movie").is_dir()
