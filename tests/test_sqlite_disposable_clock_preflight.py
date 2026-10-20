"""Disposable clock conflicts must fail before any filesystem operation."""

from datetime import datetime

import pytest

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_disposable_lifecycle_flow import execute_disposable_lifecycle_move
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore

KEY = "DISPOSABLE/Movie"


def lab(tmp_path, source_clock=True, conflict=False):
    root = tmp_path / "lab"
    root.mkdir()
    (root / ".sqlite_disposable_rehearsal").write_text("DISPOSABLE ONLY\n")
    for stage in ("transient", "holding", "removal", "keep"):
        (root / stage).mkdir()
    (root / "transient" / "Movie").mkdir()
    state = {section: {} for section in SECTIONS}
    if source_clock:
        state["first_seen"][KEY] = "2024-01-01T00:00:00"
    if conflict:
        state["queued"][KEY] = "2024-01-10T00:00:00"
    db = root / "state.db"
    write_offline_snapshot(state, db)
    return root, db


def attempt(root, db):
    return execute_disposable_lifecycle_move(
        root=root, database=db, operation_id="op-1", media_key=KEY,
        observed_at=datetime(2024, 2, 1))


@pytest.mark.parametrize("source_clock,conflict,message", [
    (False, False, "Source lifecycle clock unavailable"),
    (True, True, "Conflicting lifecycle clocks"),
    (False, True, "Source lifecycle clock unavailable"),
])
def test_invalid_clocks_block_before_intent(tmp_path, source_clock, conflict, message):
    root, db = lab(tmp_path, source_clock, conflict)
    before = RevisionedAuditSession(GuardedSQLiteStateStore(db))
    with pytest.raises(RuntimeError, match=message):
        attempt(root, db)
    after = RevisionedAuditSession(GuardedSQLiteStateStore(db))
    assert after.revision == before.revision
    assert after.state == before.state
    assert INTENTS_KEY not in after.state
    assert (root / "transient" / "Movie").is_dir()
    assert not (root / "holding" / "Movie").exists()


def test_valid_clock_still_reconciles(tmp_path):
    root, db = lab(tmp_path)
    result = attempt(root, db)
    assert result["status"] == "disposable_reconciled"
    assert KEY in RevisionedAuditSession(GuardedSQLiteStateStore(db)).state["queued"]
