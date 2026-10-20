"""Witnessed stage clock, Arr queue and intent clearance share one CAS commit."""
from datetime import datetime
import os

import pytest

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_disposable_atomic_reconcile import reconcile_witnessed_disposable_rename
from app.sqlite_operation_coordinator import SQLiteOperationCoordinator
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.state_store import GuardedSQLiteStateStore
from app.sqlite_state import SECTIONS

KEY = "Movie A"
REQUEST = {"service": "radarr", "title_id": 42, "root": "/arr/keep", "monitored": False}
NOW = datetime(2026, 1, 1)


@pytest.fixture
def moved(tmp_path):
    root = tmp_path / "lab"
    root.mkdir()
    (root / ".sqlite_disposable_rehearsal").write_text("DISPOSABLE ONLY\n")
    for stage in ("transient", "holding", "removal", "keep"):
        (root / stage).mkdir()
    source, destination = root / "transient" / KEY, root / "keep" / KEY
    source.mkdir()
    database = root / "state.db"
    state = {section: {} for section in SECTIONS}
    state["first_seen"][KEY] = "2024-01-01T00:00:00"
    write_offline_snapshot(state, database)
    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    coordinator = SQLiteOperationCoordinator(session)
    coordinator.begin_move_with_evidence("move", {
        "media_key": KEY, "source": str(source), "destination": str(destination),
        "arr_sync_request": dict(REQUEST)})
    fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY)
    try:
        source.rename(destination)
        coordinator.mark_applied("move")
        yield root, database, fd
    finally:
        os.close(fd)


def reconcile(root, database, fd, request=REQUEST):
    return reconcile_witnessed_disposable_rename(
        root=root, database=database, operation_id="move", media_key=KEY,
        source_stage="transient", destination_stage="keep", observed_at=NOW,
        witness_fd=fd, title_folder=KEY, arr_sync_request=request)


def assert_complete(state):
    assert KEY not in state["first_seen"]
    assert state["keep_seen"][KEY] == NOW.isoformat()
    assert state["arr_sync_pending"][KEY] == {"stage": "keep", **REQUEST}
    assert "sqlite_pending_operations" not in state


def test_queue_clock_and_clearance_are_one_revision(moved):
    root, database, fd = moved
    store = GuardedSQLiteStateStore(database)
    _, revision = store.load_with_revision()
    reconcile(root, database, fd)
    state, after = store.load_with_revision()
    assert after == revision + 1
    assert_complete(state)


@pytest.mark.parametrize("commit", [False, True])
def test_uncertain_commit_never_leaves_half_queue_or_clock(moved, monkeypatch, commit):
    root, database, fd = moved
    original = GuardedSQLiteStateStore.save_if_revision
    def uncertain(self, state, revision):
        if commit:
            original(self, state, revision)
        raise RuntimeError("uncertain checkpoint")
    monkeypatch.setattr(GuardedSQLiteStateStore, "save_if_revision", uncertain)
    with pytest.raises(RuntimeError, match="uncertain checkpoint"):
        reconcile(root, database, fd)
    state, _ = GuardedSQLiteStateStore(database).load_with_revision()
    if commit:
        assert_complete(state)
    else:
        assert KEY in state["first_seen"]
        assert KEY not in state["keep_seen"]
        assert KEY not in state["arr_sync_pending"]
        assert "sqlite_pending_operations" in state


@pytest.mark.parametrize("arr_request", [None, {**REQUEST, "title_id": 99}, {**REQUEST, "root": "/other"}])
def test_missing_or_changed_bound_request_never_clears_intent(moved, arr_request):
    root, database, fd = moved
    before = database.read_bytes()
    with pytest.raises(RuntimeError, match="queue request binding mismatch"):
        reconcile(root, database, fd, arr_request)
    assert database.read_bytes() == before


def test_existing_queue_entry_is_never_overwritten(moved):
    root, database, fd = moved
    store = GuardedSQLiteStateStore(database)
    state, revision = store.load_with_revision()
    state["arr_sync_pending"][KEY] = {"stage": "holding", "root": "/old", "monitored": True}
    store.save_if_revision(state, revision)
    before = database.read_bytes()
    with pytest.raises(RuntimeError, match="Existing Arr queue"):
        reconcile(root, database, fd)
    assert database.read_bytes() == before
