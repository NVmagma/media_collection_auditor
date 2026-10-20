"""Fail-closed boundaries for disposable SQLite lifecycle operations."""

from datetime import datetime
import errno

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
    (root / "transient" / "Movie").mkdir()
    (root / "transient" / "Movie" / "payload").write_text("original")
    state = {section: {} for section in SECTIONS}
    state["first_seen"][KEY] = "2024-01-01T00:00:00"
    database = root / "state.db"
    write_offline_snapshot(state, database)
    return root, database


def run(root, database):
    return execute_disposable_lifecycle_move(
        root=root, database=database, operation_id="op-1", media_key=KEY,
        observed_at=datetime(2024, 2, 1))


def state_at(database):
    return RevisionedAuditSession(GuardedSQLiteStateStore(database)).state


def test_destination_ambiguity_blocks_without_intent(tmp_path):
    root, database = setup_lab(tmp_path)
    (root / "holding" / "Movie").mkdir()
    (root / "holding" / "Movie" / "payload").write_text("other")
    with pytest.raises(RuntimeError, match="Ambiguous"):
        run(root, database)
    assert (root / "holding" / "Movie" / "payload").read_text() == "other"
    assert (root / "transient" / "Movie" / "payload").read_text() == "original"
    assert INTENTS_KEY not in state_at(database)


def test_cross_device_rename_error_preserves_intent_and_source(tmp_path, monkeypatch):
    root, database = setup_lab(tmp_path)
    import app.sqlite_disposable_lifecycle_flow as flow

    def cross_device(*_args):
        raise OSError(errno.EXDEV, "cross-device")

    monkeypatch.setattr(flow, "rename_directory_noreplace", cross_device)
    with pytest.raises(RuntimeError, match="Cross-device"):
        run(root, database)
    assert (root / "transient" / "Movie" / "payload").read_text() == "original"
    assert INTENTS_KEY in state_at(database)
    assert KEY in state_at(database)["first_seen"]


def test_stale_revision_never_overwrites_newer_snapshot(tmp_path):
    root, database = setup_lab(tmp_path)
    stale = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    newer = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    newer.state["custom_note"] = {"preserve": "newer"}
    newer.checkpoint()
    stale.state["custom_note"] = {"preserve": "stale"}
    with pytest.raises(RuntimeError):
        stale.checkpoint()
    assert state_at(database)["custom_note"] == {"preserve": "newer"}
    assert INTENTS_KEY not in state_at(database)


def test_failed_checkpoint_invalidates_session(tmp_path):
    root, database = setup_lab(tmp_path)
    stale = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    newer = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    newer.state["custom_note"] = "new"
    newer.checkpoint()
    with pytest.raises(RuntimeError):
        stale.checkpoint()
    with pytest.raises(RuntimeError, match="invalid"):
        stale.read_verified_snapshot()
