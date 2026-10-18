"""Persisted recovery diagnostics on disposable media and databases."""

import json

import pytest

from app.sqlite_audit_bootstrap import open_isolated_sqlite_audit
from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_migration import create_offline_migration_snapshot
from app.sqlite_operation_coordinator import INTENTS_KEY, SQLiteOperationCoordinator
from app.sqlite_persisted_recovery import inspect_persisted_recovery
from app.state_store import GuardedSQLiteStateStore


def _setup(tmp_path):
    source = tmp_path / "source.json"
    backup = tmp_path / "backup.json"
    database = tmp_path / "state.db"
    original = json.dumps({
        "first_seen": {"Movie": "2024-01-01T01:02:03"},
        "legacy": {"history": ["waiting", "keep"]},
    }).encode()
    source.write_bytes(original)
    create_offline_migration_snapshot(source, backup, database)
    return source, backup, database, original


def _evidence():
    return {
        "available": True, "complete": True,
        "keep": False, "keep_forever": False,
        "keep_all_seasons": False, "favorite": False,
    }


def test_disposable_move_recovery_stays_blocked_after_restart(tmp_path):
    source, backup, database, original = _setup(tmp_path)
    waiting = tmp_path / "Waiting" / "Movie"
    target = tmp_path / "Keep" / "Movie"
    waiting.mkdir(parents=True)
    target.parent.mkdir()
    (waiting / "fixture.txt").write_text("only test media")
    coordinator = SQLiteOperationCoordinator(open_isolated_sqlite_audit(source, backup, database))
    coordinator.begin("move-1", "move", {
        "source": str(waiting), "destination": str(target),
    })
    waiting.rename(target)
    before = database.read_bytes()
    report = inspect_persisted_recovery(database, jellyfin_evidence=_evidence())
    assert report["id"] == "move-1"
    assert report["observation"] == "destination_present"
    assert report["authorization"] == "blocked_pending_independent_verification"
    assert report["production_activation"] == "disabled"
    assert database.read_bytes() == before
    assert source.read_bytes() == backup.read_bytes() == original
    assert (target / "fixture.txt").exists()
    reopened = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    assert reopened.state[INTENTS_KEY]["phase"] == "intent_recorded"
    with pytest.raises(RuntimeError, match="trusted verification"):
        SQLiteOperationCoordinator(reopened).reconcile("move-1", reopened.state)


def test_missing_jellyfin_evidence_never_authorizes(tmp_path):
    _, _, database, _ = _setup(tmp_path)
    session = open_isolated_sqlite_audit(*_paths(tmp_path))
    waiting = tmp_path / "Waiting" / "Movie"
    target = tmp_path / "Keep" / "Movie"
    waiting.mkdir(parents=True)
    target.parent.mkdir()
    SQLiteOperationCoordinator(session).begin("move-1", "move", {
        "source": str(waiting), "destination": str(target),
    })
    report = inspect_persisted_recovery(database, jellyfin_evidence=None)
    assert report["authorization"] == "blocked_pending_independent_verification"


def _paths(tmp_path):
    return tmp_path / "source.json", tmp_path / "backup.json", tmp_path / "state.db"


def test_arr_recovery_reports_match_but_cannot_clear(tmp_path):
    source, backup, database, original = _setup(tmp_path)
    session = open_isolated_sqlite_audit(source, backup, database)
    coordinator = SQLiteOperationCoordinator(session)
    coordinator.begin("sync-1", "arr_sync", {
        "service": "radarr", "title_id": 17,
        "root": "/media/Movies_keep", "monitored": True,
    })
    coordinator.mark_applied("sync-1")
    record = {"id": 17, "path": "/media/Movies_keep/Movie", "monitored": True}
    report = inspect_persisted_recovery(
        database, jellyfin_evidence=_evidence(), arr_record=record
    )
    assert report["observation"] == "matching_record_unverified"
    assert report["authorization"] == "blocked_pending_independent_verification"
    assert report["revision"] == 2
    assert source.read_bytes() == backup.read_bytes() == original
    reopened = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    assert reopened.state[INTENTS_KEY]["phase"] == "applied_pending_reconciliation"


def test_stale_reconciliation_is_rejected_before_phase_checks(tmp_path):
    source, backup, database, _ = _setup(tmp_path)
    first = open_isolated_sqlite_audit(source, backup, database)
    stale = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    SQLiteOperationCoordinator(first).begin("move-1", "move", {
        "source": "/disposable/Waiting/Movie",
        "destination": "/disposable/Keep/Movie",
    })
    with pytest.raises(RuntimeError, match="stale"):
        SQLiteOperationCoordinator(stale).reconcile("move-1", {})
    assert GuardedSQLiteStateStore(database).load_with_revision()[0][INTENTS_KEY]["id"] == "move-1"
