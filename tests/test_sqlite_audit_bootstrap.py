"""Disposable end-to-end bootstrap checks, without media side effects."""

import json

import pytest

from app.sqlite_audit_bootstrap import open_isolated_sqlite_audit
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS


def _setup(tmp_path):
    source = tmp_path / "state.json"
    backup = tmp_path / "backup.json"
    database = tmp_path / "state.db"
    state = {section: {} for section in SECTIONS}
    state["first_seen"]["Movie"] = "2024-01-01T00:00:00"
    state["legacy"] = {"unknown": True}
    source.write_text(json.dumps(state))
    backup.write_bytes(source.read_bytes())
    write_offline_snapshot(state, database)
    return source, backup, database, state


def test_bootstrap_preserves_tracking_and_supports_guarded_checkpoint(tmp_path):
    source, backup, database, original = _setup(tmp_path)
    session = open_isolated_sqlite_audit(source, backup, database)
    assert session.state == original
    assert session.revision == 0
    session.state["arr_sync_pending"]["Movie"] = {
        "stage": "keep", "root": "/media/Movies_keep", "monitored": False
    }
    session.checkpoint()
    assert session.revision == 1
    assert session.state["legacy"] == original["legacy"]


def test_bootstrap_rejects_corrupt_backup_before_any_write(tmp_path):
    source, backup, database, original = _setup(tmp_path)
    backup.write_text("{}")
    with pytest.raises(RuntimeError):
        open_isolated_sqlite_audit(source, backup, database)
    assert source.read_bytes() != backup.read_bytes()


def test_bootstrap_rejects_already_modified_sqlite(tmp_path):
    source, backup, database, _ = _setup(tmp_path)
    session = open_isolated_sqlite_audit(source, backup, database)
    session.checkpoint()
    with pytest.raises(RuntimeError, match="already modified"):
        open_isolated_sqlite_audit(source, backup, database)


def test_bootstrap_rejects_missing_database(tmp_path):
    source, backup, database, _ = _setup(tmp_path)
    database.unlink()
    with pytest.raises(RuntimeError):
        open_isolated_sqlite_audit(source, backup, database)
    assert not database.exists()


@pytest.mark.parametrize("section", [
    "first_seen", "queued", "in_removal", "keep_seen",
])
def test_isolated_lifecycle_transition_persists_without_erasing_other_sections(
    tmp_path, section,
):
    """Each lifecycle tracking section survives a guarded SQLite checkpoint."""
    from app.sqlite_audit_session import RevisionedAuditSession
    from app.state_store import GuardedSQLiteStateStore

    source, backup, database, original = _setup(tmp_path)
    session = open_isolated_sqlite_audit(source, backup, database)
    for index, name in enumerate(("first_seen", "queued", "in_removal", "keep_seen")):
        session.state[name][f"historical-{index}"] = "2025-01-01T00:00:00"
    session.state[section]["new-title"] = "2025-02-01T00:00:00"
    session.state["arr_sync_pending"]["new-title"] = {
        "stage": "keep" if section == "keep_seen" else "holding",
        "root": "/media/disposable_only", "monitored": False,
    }
    session.checkpoint()
    restarted = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    assert restarted.revision == 1
    assert restarted.state == session.state
    assert restarted.state["legacy"] == original["legacy"]
    for index, name in enumerate(("first_seen", "queued", "in_removal", "keep_seen")):
        assert restarted.state[name][f"historical-{index}"] == "2025-01-01T00:00:00"
    assert restarted.state[section]["new-title"] == "2025-02-01T00:00:00"
    assert source.read_bytes() == backup.read_bytes()


def test_isolated_sqlite_rejects_stale_lifecycle_writer(tmp_path):
    """A second session cannot silently overwrite a newer lifecycle change."""
    from app.sqlite_audit_session import RevisionedAuditSession
    from app.state_store import GuardedSQLiteStateStore

    source, backup, database, _ = _setup(tmp_path)
    first = open_isolated_sqlite_audit(source, backup, database)
    stale = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    first.state["keep_seen"]["Protected Show"] = "2025-01-01T00:00:00"
    first.checkpoint()
    stale.state["in_removal"]["Protected Show"] = "2025-02-01T00:00:00"
    with pytest.raises(RuntimeError):
        stale.checkpoint()
    verified = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    assert "Protected Show" in verified.state["keep_seen"]
    assert "Protected Show" not in verified.state["in_removal"]
    assert source.read_bytes() == backup.read_bytes()
    with pytest.raises(RuntimeError, match="invalid after failed checkpoint"):
        stale.checkpoint()


@pytest.mark.parametrize("stage", ["holding", "keep", "removal"])
def test_arr_retry_stage_roundtrip_preserves_tracking_and_legacy(tmp_path, stage):
    from app.sqlite_audit_session import RevisionedAuditSession
    from app.state_store import GuardedSQLiteStateStore

    source, backup, database, original = _setup(tmp_path)
    session = open_isolated_sqlite_audit(source, backup, database)
    session.state["arr_sync_pending"]["pending-item"] = {
        "stage": stage, "root": "/media/disposable_only",
        "monitored": True,
    }
    session.checkpoint()
    restarted = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    assert restarted.state["arr_sync_pending"]["pending-item"]["stage"] == stage
    assert restarted.state["legacy"] == original["legacy"]
    assert restarted.state["first_seen"] == original["first_seen"]
    assert source.read_bytes() == backup.read_bytes()


@pytest.mark.parametrize("kind", ["move", "arr_sync"])
@pytest.mark.parametrize("phase", ["intent_recorded", "applied_pending_reconciliation"])
def test_bootstrap_blocks_unresolved_operation_after_restart(tmp_path, kind, phase):
    """Neither a pending filesystem move nor an Arr call permits new bootstrap."""
    from app.sqlite_operation_coordinator import SQLiteOperationCoordinator
    from app.sqlite_audit_session import RevisionedAuditSession
    from app.state_store import GuardedSQLiteStateStore

    source, backup, database, original = _setup(tmp_path)
    session = open_isolated_sqlite_audit(source, backup, database)
    coordinator = SQLiteOperationCoordinator(session)
    coordinator.begin("disposable-pending", kind, {"media": "DISPOSABLE/Example"})
    if phase == "applied_pending_reconciliation":
        coordinator.mark_applied("disposable-pending")
    before = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    before_revision = before.revision
    before_state = before.read_verified_snapshot()[0]

    with pytest.raises(RuntimeError, match="already modified"):
        open_isolated_sqlite_audit(source, backup, database)

    after = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    assert after.revision == before_revision
    assert after.state == before_state
    assert after.state["sqlite_pending_operations"]["phase"] == phase
    assert source.read_bytes() == backup.read_bytes()
    assert original["first_seen"] == after.state["first_seen"]


def test_bootstrap_refuses_diverged_database_without_mutating_artifacts(tmp_path):
    """Parity is a prerequisite, not permission to overwrite changed SQLite state."""
    from app.sqlite_audit_session import RevisionedAuditSession
    from app.state_store import GuardedSQLiteStateStore

    source, backup, database, _ = _setup(tmp_path)
    session = open_isolated_sqlite_audit(source, backup, database)
    session.state["keep_seen"]["DISPOSABLE/Example"] = "2025-01-01T00:00:00"
    session.checkpoint()
    before = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    before_state, before_revision = before.read_verified_snapshot()

    with pytest.raises(RuntimeError):
        open_isolated_sqlite_audit(source, backup, database)

    after = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    assert after.revision == before_revision
    assert after.state == before_state
    assert source.read_bytes() == backup.read_bytes()
