"""Readiness is read-only, fail-closed, and never production authorization."""

from app import sqlite_readiness
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore


def _baseline(tmp_path, pending=False):
    path = tmp_path / "audit.db"
    state = {section: {} for section in SECTIONS}
    if pending:
        state[INTENTS_KEY] = {
            "id": "move-1", "kind": "move", "phase": "intent_recorded",
            "details": {"source": "/media/Waiting/Movie"},
        }
    write_offline_snapshot(state, path)
    store = GuardedSQLiteStateStore(path)
    baseline, revision = store.load_with_revision()
    return store, baseline, revision


def test_clean_isolated_snapshot_reports_review_only(tmp_path, monkeypatch):
    store, baseline, revision = _baseline(tmp_path)
    monkeypatch.setattr(sqlite_readiness, "prepare_sqlite_audit_state",
                        lambda *args: (store, baseline, revision))
    report = sqlite_readiness.inspect_sqlite_readiness("source", "backup", "db")
    assert report["ready_for_isolated_review"] is True
    assert report["production_activation"] == "disabled"
    assert report["storage_authority"] == "json"
    assert report["revision"] == revision
    assert report["blockers"] == []
    assert store.load_with_revision() == (baseline, revision)


def test_pending_operation_blocks_review(tmp_path, monkeypatch):
    store, baseline, revision = _baseline(tmp_path, pending=True)
    monkeypatch.setattr(sqlite_readiness, "prepare_sqlite_audit_state",
                        lambda *args: (store, baseline, revision))
    report = sqlite_readiness.inspect_sqlite_readiness("source", "backup", "db")
    assert not report["ready_for_isolated_review"]
    assert report["blockers"] == ["unresolved_operation_requires_reconciliation"]
    assert report["revision"] is None
    assert store.load_with_revision() == (baseline, revision)


def test_stale_snapshot_blocks_review(tmp_path, monkeypatch):
    store, baseline, revision = _baseline(tmp_path)
    store.save_if_revision({**baseline, "other": "updated"}, revision)
    monkeypatch.setattr(sqlite_readiness, "prepare_sqlite_audit_state",
                        lambda *args: (store, baseline, revision))
    report = sqlite_readiness.inspect_sqlite_readiness("source", "backup", "db")
    assert report["blockers"] == ["state_changed_during_inspection"]
    assert not report["ready_for_isolated_review"]


def test_missing_artifacts_fail_closed(tmp_path):
    report = sqlite_readiness.inspect_sqlite_readiness(
        tmp_path / "missing.json", tmp_path / "missing.bak", tmp_path / "missing.db"
    )
    assert report["blockers"] == ["migration_or_snapshot_verification_failed"]
    assert not report["ready_for_isolated_review"]
    assert report["production_activation"] == "disabled"
