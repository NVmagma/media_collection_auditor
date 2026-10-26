"""The legacy disposable runner must not bypass atomic no-replace semantics."""

import errno
from pathlib import Path

import pytest

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_disposable_move_runner import rehearse_disposable_move
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore


def setup_lab(tmp_path):
    root = tmp_path / "lab"
    root.mkdir()
    (root / ".sqlite_disposable_rehearsal").write_text("DISPOSABLE ONLY\n")
    for stage in ("transient", "holding", "removal", "keep"):
        (root / stage).mkdir()
    (root / "transient" / "Movie").mkdir()
    (root / "transient" / "Movie" / "payload").write_text("original")
    state = {section: {} for section in SECTIONS}
    state["first_seen"]["DISPOSABLE/Movie"] = "2024-01-01T00:00:00"
    database = root / "state.db"
    write_offline_snapshot(state, database)
    return root, database


def run(root, database):
    return rehearse_disposable_move(
        root=root, database=database, operation_id="op-1",
        media_key="DISPOSABLE/Movie")


def state_at(database):
    return RevisionedAuditSession(GuardedSQLiteStateStore(database)).state


def test_legacy_runner_rejects_destination_created_after_intent(tmp_path, monkeypatch):
    import app.sqlite_disposable_move_runner as runner
    root, database = setup_lab(tmp_path)
    actual = runner.rename_directory_noreplace

    def concurrent_creation(source, destination):
        destination = Path(destination)
        destination.mkdir()
        (destination / "payload").write_text("other")
        actual(source, destination)

    monkeypatch.setattr(runner, "rename_directory_noreplace", concurrent_creation)
    with pytest.raises(OSError):
        run(root, database)
    assert (root / "transient" / "Movie" / "payload").read_text() == "original"
    assert (root / "holding" / "Movie" / "payload").read_text() == "other"
    assert state_at(database)[INTENTS_KEY]["phase"] == "intent_recorded"


def test_legacy_runner_unsupported_rename_preserves_intent(tmp_path, monkeypatch):
    import app.sqlite_disposable_move_runner as runner
    root, database = setup_lab(tmp_path)

    def unsupported(*_args):
        raise RuntimeError("Atomic no-replace rename unsupported")

    monkeypatch.setattr(runner, "rename_directory_noreplace", unsupported)
    with pytest.raises(RuntimeError, match="unsupported"):
        run(root, database)
    assert (root / "transient" / "Movie").is_dir()
    assert not (root / "holding" / "Movie").exists()
    assert state_at(database)[INTENTS_KEY]["phase"] == "intent_recorded"


def test_legacy_runner_still_moves_disposable_title(tmp_path):
    root, database = setup_lab(tmp_path)
    result = run(root, database)
    assert result["status"] == "pending_reconciliation"
    assert (root / "holding" / "Movie" / "payload").read_text() == "original"
    assert state_at(database)[INTENTS_KEY]["phase"] == "applied_pending_reconciliation"
