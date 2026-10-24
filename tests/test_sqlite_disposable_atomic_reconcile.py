"""Disposable in-process witness and atomic reconciliation tests."""

from datetime import datetime
import os

import pytest

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_disposable_atomic_reconcile import reconcile_witnessed_disposable_rename
from app.sqlite_operation_coordinator import INTENTS_KEY, SQLiteOperationCoordinator
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore

KEY = "DISPOSABLE/Movie"


def _fixture(tmp_path):
    root = tmp_path / "lab"
    root.mkdir()
    (root / ".sqlite_disposable_rehearsal").write_text("DISPOSABLE ONLY\n")
    for stage in ("transient", "holding", "removal", "keep"):
        (root / stage).mkdir()
    source = root / "transient" / "Movie"
    source.mkdir()
    (source / "marker").write_text("test")
    database = root / "state.db"
    state = {section: {} for section in SECTIONS}
    state["first_seen"][KEY] = "2024-01-01T00:00:00"
    write_offline_snapshot(state, database)
    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    coordinator = SQLiteOperationCoordinator(session)
    coordinator.begin_move_with_evidence(
        "op-1", {"media_key": KEY, "source": str(source),
                 "destination": str(root / "holding" / "Movie")})
    return root, database, coordinator


def _reconcile(root, database, fd):
    snapshot, revision = GuardedSQLiteStateStore(database).load_with_revision()
    return reconcile_witnessed_disposable_rename(
        root=root, database=database, operation_id="op-1",
        media_key=KEY, source_stage="transient",
        destination_stage="holding", observed_at=datetime(2024, 2, 1),
        witness_fd=fd, expected_revision=revision, expected_snapshot=snapshot)


def _state(database):
    return RevisionedAuditSession(GuardedSQLiteStateStore(database)).state


def test_live_witness_allows_one_atomic_disposable_checkpoint(tmp_path):
    root, database, coordinator = _fixture(tmp_path)
    source = root / "transient" / "Movie"
    fd = os.open(source, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        source.rename(root / "holding" / "Movie")
        coordinator.mark_applied("op-1")
        result = _reconcile(root, database, fd)
    finally:
        os.close(fd)
    assert result["status"] == "disposable_reconciled"
    assert result["production_activation"] == "disabled"
    state = _state(database)
    assert INTENTS_KEY not in state
    assert KEY not in state["first_seen"]
    assert state["queued"][KEY] == "2024-02-01T00:00:00"
    assert (root / "holding" / "Movie" / "marker").read_text() == "test"


def test_restart_without_live_witness_never_clears_intent(tmp_path):
    root, database, coordinator = _fixture(tmp_path)
    (root / "transient" / "Movie").rename(root / "holding" / "Movie")
    coordinator.mark_applied("op-1")
    with pytest.raises(RuntimeError, match="witness"):
        _reconcile(root, database, -1)
    assert INTENTS_KEY in _state(database)
    assert KEY in _state(database)["first_seen"]


def test_unapplied_intent_does_not_clear_even_with_witness(tmp_path):
    root, database, _ = _fixture(tmp_path)
    source = root / "transient" / "Movie"
    fd = os.open(source, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        source.rename(root / "holding" / "Movie")
        with pytest.raises(RuntimeError, match="Persisted intent"):
            _reconcile(root, database, fd)
    finally:
        os.close(fd)
    assert INTENTS_KEY in _state(database)


def test_unrelated_witness_cannot_clear_intent(tmp_path):
    root, database, coordinator = _fixture(tmp_path)
    fd = os.open(root / "keep", os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        (root / "transient" / "Movie").rename(root / "holding" / "Movie")
        coordinator.mark_applied("op-1")
        with pytest.raises(RuntimeError, match="Witness does not match"):
            _reconcile(root, database, fd)
    finally:
        os.close(fd)
    assert INTENTS_KEY in _state(database)


def test_missing_marker_never_clears_intent(tmp_path):
    root, database, coordinator = _fixture(tmp_path)
    source = root / "transient" / "Movie"
    fd = os.open(source, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        source.rename(root / "holding" / "Movie")
        coordinator.mark_applied("op-1")
        (root / ".sqlite_disposable_rehearsal").unlink()
        with pytest.raises(RuntimeError, match="marker"):
            _reconcile(root, database, fd)
    finally:
        os.close(fd)
    assert INTENTS_KEY in _state(database)


@pytest.mark.parametrize("binding", [None, {}, {
    "source_stage": "transient", "destination_stage": "holding",
    "source_timestamp": "2024-01-01T00:00:00", "observed_at": "2024-03-01T00:00:00",
}])
def test_required_clock_binding_rejects_absent_or_changed_plan(tmp_path, binding):
    root, database, coordinator = _fixture(tmp_path)
    source = root / "transient" / "Movie"
    fd = os.open(source, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        source.rename(root / "holding" / "Movie")
        coordinator.mark_applied("op-1")
        store = GuardedSQLiteStateStore(database)
        state, revision = store.load_with_revision()
        if binding is not None:
            state[INTENTS_KEY]["details"]["lifecycle_clock_binding"] = binding
            store.save_if_revision(state, revision)
        before = database.read_bytes()
        with pytest.raises(RuntimeError, match="clock binding mismatch"):
            expected, expected_revision = store.load_with_revision()
            reconcile_witnessed_disposable_rename(
                root=root, database=database, operation_id="op-1", media_key=KEY,
                source_stage="transient", destination_stage="holding",
                observed_at=datetime(2024, 2, 1), witness_fd=fd, require_clock_binding=True,
                expected_revision=expected_revision, expected_snapshot=expected)
        assert database.read_bytes() == before
        assert INTENTS_KEY in _state(database)
    finally:
        os.close(fd)


def test_matching_required_clock_binding_commits_atomically(tmp_path):
    root, database, coordinator = _fixture(tmp_path)
    source = root / "transient" / "Movie"
    fd = os.open(source, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        source.rename(root / "holding" / "Movie")
        coordinator.mark_applied("op-1")
        store = GuardedSQLiteStateStore(database)
        state, revision = store.load_with_revision()
        state[INTENTS_KEY]["details"]["lifecycle_clock_binding"] = {
            "source_stage": "transient", "destination_stage": "holding",
            "source_timestamp": "2024-01-01T00:00:00", "observed_at": "2024-02-01T00:00:00",
        }
        store.save_if_revision(state, revision)
        expected, expected_revision = store.load_with_revision()
        reconcile_witnessed_disposable_rename(
            root=root, database=database, operation_id="op-1", media_key=KEY,
            source_stage="transient", destination_stage="holding",
            observed_at=datetime(2024, 2, 1), witness_fd=fd, require_clock_binding=True,
            expected_revision=expected_revision, expected_snapshot=expected)
        after, after_revision = store.load_with_revision()
        assert after_revision == revision + 2
        assert KEY not in after["first_seen"]
        assert after["queued"][KEY] == "2024-02-01T00:00:00"
        assert INTENTS_KEY not in after
    finally:
        os.close(fd)


@pytest.mark.parametrize('change_revision', [False, True])
def test_exact_applied_binding_rejects_intervening_state_without_clearance(tmp_path, change_revision):
    import sqlite3
    root, database, coordinator = _fixture(tmp_path)
    fd = os.open(root / 'transient/Movie', os.O_RDONLY | os.O_DIRECTORY)
    try:
        (root / 'transient/Movie').rename(root / 'holding/Movie')
        coordinator.mark_applied('op-1')
        store = GuardedSQLiteStateStore(database)
        expected, revision = store.load_with_revision()
        if change_revision:
            changed = {**expected, 'intervening_writer': {'preserve': True}}
            store.save_if_revision(changed, revision)
        else:
            connection = sqlite3.connect(database)
            try:
                connection.execute('INSERT INTO extra_state (key,value_json) VALUES (?,?)',
                                   ('intervening_writer', '{"preserve":true}'))
                connection.commit()
            finally: connection.close()
        before = database.read_bytes()
        with pytest.raises(RuntimeError, match='state changed'):
            reconcile_witnessed_disposable_rename(root=root, database=database,
                operation_id='op-1', media_key=KEY, source_stage='transient',
                destination_stage='holding', observed_at=datetime(2024, 2, 1), witness_fd=fd,
                expected_revision=revision, expected_snapshot=expected)
        assert database.read_bytes() == before
        current, _ = store.load_with_revision()
        assert current['intervening_writer'] == {'preserve': True}
        assert INTENTS_KEY in current and KEY in current['first_seen']
        assert KEY not in current['queued']
    finally: os.close(fd)
