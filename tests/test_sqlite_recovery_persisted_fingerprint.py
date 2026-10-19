"""Persisted move evidence inspection must stay read-only and blocked."""

import pytest

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_operation_coordinator import INTENTS_KEY, SQLiteOperationCoordinator
from app.sqlite_recovery_persisted_fingerprint import inspect_persisted_move_evidence
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore


def setup_move(tmp_path):
    database = tmp_path / "state.db"
    write_offline_snapshot({section: {} for section in SECTIONS}, database)
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.mkdir()
    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    SQLiteOperationCoordinator(session).begin_move_with_evidence(
        "move-1", {"source": str(source), "destination": str(destination)}
    )
    return database, source, destination


def test_persisted_evidence_survives_restart_and_never_authorizes(tmp_path):
    database, source, destination = setup_move(tmp_path)
    report = inspect_persisted_move_evidence(database)
    assert report["evidence_verification"] == "schema_valid_untrusted"
    assert report["source_fingerprint"] == "metadata_consistent_unverified"
    assert report["destination_fingerprint"] == "unverified"
    assert report["destination_reason"] == "fingerprint_unavailable"
    assert report["authorization"] == "not_authorized"
    assert report["reconciliation"] == "disabled"
    assert str(source) not in str(report)
    assert "inode" not in str(report)


def test_destination_copy_cannot_prove_completed_move(tmp_path):
    database, source, destination = setup_move(tmp_path)
    destination.mkdir()
    report = inspect_persisted_move_evidence(database)
    assert report["destination_fingerprint"] == "unverified"
    assert report["authorization"] == "not_authorized"


def test_missing_source_after_move_remains_blocked(tmp_path):
    database, source, destination = setup_move(tmp_path)
    source.rename(destination)
    report = inspect_persisted_move_evidence(database)
    assert report["source_fingerprint"] == "unverified"
    assert report["authorization"] == "not_authorized"
    assert report["reconciliation"] == "disabled"


def test_absent_evidence_is_reported_without_authorizing(tmp_path):
    database = tmp_path / "state.db"
    write_offline_snapshot({section: {} for section in SECTIONS}, database)
    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    SQLiteOperationCoordinator(session).begin(
        "move-old", "move", {"source": "/missing", "destination": "/also-missing"}
    )
    report = inspect_persisted_move_evidence(database)
    assert report["evidence_reason"] == "invalid_evidence_envelope"
    assert report["authorization"] == "not_authorized"


def test_no_pending_move_is_rejected(tmp_path):
    database = tmp_path / "state.db"
    write_offline_snapshot({section: {} for section in SECTIONS}, database)
    with pytest.raises(RuntimeError, match="Pending move unavailable"):
        inspect_persisted_move_evidence(database)


def test_snapshot_change_during_inspection_fails_closed(tmp_path, monkeypatch):
    database, _, _ = setup_move(tmp_path)
    import app.sqlite_recovery_persisted_fingerprint as module
    original = module.capture_directory_fingerprint
    calls = 0
    def changed(path):
        nonlocal calls
        calls += 1
        if calls == 1:
            store = GuardedSQLiteStateStore(database)
            state, revision = store.load_with_revision()
            state["new_unrelated_state"] = {"changed": True}
            store.save_if_revision(state, revision)
        return original(path)
    monkeypatch.setattr(module, "capture_directory_fingerprint", changed)
    with pytest.raises(RuntimeError, match="stale"):
        inspect_persisted_move_evidence(database)
