"""Disposable media restart rehearsals: SQLite never replays pending moves."""

import pytest

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_operation_coordinator import INTENTS_KEY, SQLiteOperationCoordinator
from app.sqlite_recovery_filesystem import inspect_pending_move_filesystem
from app.sqlite_recovery_offline_evidence import inspect_offline_move_evidence
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore


@pytest.mark.parametrize("phase", ["intent_recorded", "applied_pending_reconciliation"])
@pytest.mark.parametrize("location", ["source_only", "both_present", "destination_only"])
def test_disposable_media_restart_never_replays_or_clears(tmp_path, phase, location):
    database = tmp_path / "state.db"
    source, destination = tmp_path / "waiting" / "Film", tmp_path / "keep" / "Film"
    source.parent.mkdir()
    destination.parent.mkdir()
    source.mkdir()
    (source / "sample.txt").write_text("disposable movie fixture")
    write_offline_snapshot({section: {} for section in SECTIONS}, database)
    coordinator = SQLiteOperationCoordinator(RevisionedAuditSession(GuardedSQLiteStateStore(database)))
    coordinator.begin_move_with_evidence("disposable-move", {
        "source": str(source), "destination": str(destination),
    })
    if phase == "applied_pending_reconciliation":
        coordinator.mark_applied("disposable-move")
    if location == "both_present":
        destination.mkdir()
        (destination / "sample.txt").write_text("different disposable fixture")
    elif location == "destination_only":
        source.rename(destination)
    before_source = (source / "sample.txt").read_bytes() if source.exists() else None
    before_destination = ((destination / "sample.txt").read_bytes()
                          if destination.exists() else None)
    before_revision = RevisionedAuditSession(GuardedSQLiteStateStore(database)).revision

    # New session simulates process restart. Diagnostics must not alter fixtures.
    restarted = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    assert restarted.state[INTENTS_KEY]["phase"] == phase
    report = inspect_pending_move_filesystem(database)
    evidence = inspect_offline_move_evidence(database)
    assert report["authorization"] == "not_authorized"
    assert evidence["decision"]["authorization"] == "not_authorized"
    assert evidence["reconciliation"] == "disabled"
    with pytest.raises(RuntimeError, match="Unresolved"):
        SQLiteOperationCoordinator(restarted).begin(
            "new-move", "move", {"source": str(source), "destination": str(destination)}
        )
    if phase == "applied_pending_reconciliation":
        with pytest.raises(RuntimeError, match="blocked pending trusted verification"):
            SQLiteOperationCoordinator(restarted).reconcile("disposable-move", restarted.state)
    assert ((source / "sample.txt").read_bytes()
            if source.exists() else None) == before_source
    assert ((destination / "sample.txt").read_bytes()
            if destination.exists() else None) == before_destination
    latest = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    assert latest.revision == before_revision
    assert latest.state[INTENTS_KEY]["phase"] == phase


@pytest.mark.parametrize("phase", ["intent_recorded", "applied_pending_reconciliation"])
def test_arr_sync_pending_restart_blocks_new_operations(tmp_path, phase):
    """A crash cannot silently retry an Arr action or clear its intent."""
    database = tmp_path / "state.db"
    write_offline_snapshot({section: {} for section in SECTIONS}, database)
    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    coordinator = SQLiteOperationCoordinator(session)
    coordinator.begin("disposable-arr-sync", "arr_sync", {
        "media": "DISPOSABLE/Example", "stage": "keep",
    })
    if phase == "applied_pending_reconciliation":
        coordinator.mark_applied("disposable-arr-sync")

    restarted = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    before_revision = restarted.revision
    before_state = restarted.read_verified_snapshot()[0]
    assert before_state[INTENTS_KEY]["phase"] == phase
    with pytest.raises(RuntimeError, match="Unresolved"):
        SQLiteOperationCoordinator(restarted).begin(
            "second-arr-sync", "arr_sync", {"media": "DISPOSABLE/Other"}
        )
    if phase == "applied_pending_reconciliation":
        with pytest.raises(RuntimeError, match="blocked pending trusted verification"):
            SQLiteOperationCoordinator(restarted).reconcile(
                "disposable-arr-sync", before_state
            )
    fresh = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    assert fresh.revision == before_revision
    assert fresh.state == before_state


def test_concurrent_arr_intents_preserve_first_committed_operation(tmp_path):
    """A stale session cannot replace a durable, unresolved Arr intent."""
    database = tmp_path / "state.db"
    write_offline_snapshot({section: {} for section in SECTIONS}, database)
    first = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    stale = RevisionedAuditSession(GuardedSQLiteStateStore(database))

    SQLiteOperationCoordinator(first).begin(
        "first-arr", "arr_sync", {"media": "DISPOSABLE/First", "stage": "keep"}
    )
    with pytest.raises(RuntimeError, match="stale"):
        SQLiteOperationCoordinator(stale).begin(
            "second-arr", "arr_sync", {"media": "DISPOSABLE/Second", "stage": "keep"}
        )

    reopened = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    assert reopened.state[INTENTS_KEY]["id"] == "first-arr"
    assert reopened.state[INTENTS_KEY]["phase"] == "intent_recorded"
    with pytest.raises(RuntimeError, match="Unresolved"):
        SQLiteOperationCoordinator(reopened).begin(
            "third-arr", "arr_sync", {"media": "DISPOSABLE/Third"}
        )
    verified = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    assert verified.state[INTENTS_KEY]["id"] == "first-arr"
    assert verified.revision == first.revision
