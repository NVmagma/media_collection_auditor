"""Disposable end-to-end move execution with crash fault injection."""

from pathlib import Path

import pytest

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_disposable_move_runner import rehearse_disposable_move
from app.sqlite_operation_coordinator import INTENTS_KEY
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
    (source / "payload.txt").write_text("test-only")
    state = {section: {} for section in SECTIONS}
    state["first_seen"][KEY] = "2024-01-01T00:00:00"
    database = root / "state.db"
    write_offline_snapshot(state, database)
    return root, database


def _run(root, database, **kwargs):
    return rehearse_disposable_move(
        root=root, database=database, operation_id="op-1",
        media_key=KEY, **kwargs)


def _state(database):
    return RevisionedAuditSession(GuardedSQLiteStateStore(database)).state


def test_end_to_end_rename_leaves_applied_intent_and_original_clock(tmp_path):
    root, database = _fixture(tmp_path)
    result = _run(root, database)
    assert result["status"] == "pending_reconciliation"
    assert result["intent_clearance"] == "blocked"
    assert (root / "holding" / "Movie" / "payload.txt").read_text() == "test-only"
    assert not (root / "transient" / "Movie").exists()
    assert _state(database)[INTENTS_KEY]["phase"] == "applied_pending_reconciliation"
    assert KEY in _state(database)["first_seen"]
    assert KEY not in _state(database)["queued"]
    with pytest.raises(RuntimeError):
        _run(root, database)


def test_crash_after_intent_keeps_source_and_pending_intent(tmp_path):
    root, database = _fixture(tmp_path)
    def crash():
        raise RuntimeError("crash after intent")
    with pytest.raises(RuntimeError, match="crash after intent"):
        _run(root, database, after_intent=crash)
    assert (root / "transient" / "Movie").is_dir()
    assert _state(database)[INTENTS_KEY]["phase"] == "intent_recorded"
    with pytest.raises(RuntimeError):
        _run(root, database)


def test_crash_after_rename_keeps_unresolved_intent(tmp_path):
    root, database = _fixture(tmp_path)
    def crash():
        raise RuntimeError("crash after rename")
    with pytest.raises(RuntimeError, match="crash after rename"):
        _run(root, database, after_rename=crash)
    assert (root / "holding" / "Movie").is_dir()
    assert _state(database)[INTENTS_KEY]["phase"] == "intent_recorded"
    assert KEY in _state(database)["first_seen"]


def test_marker_missing_prevents_any_operation(tmp_path):
    root, database = _fixture(tmp_path)
    (root / ".sqlite_disposable_rehearsal").unlink()
    before = database.read_bytes()
    with pytest.raises(RuntimeError, match="marker"):
        _run(root, database)
    assert database.read_bytes() == before
    assert (root / "transient" / "Movie").is_dir()


def test_symlinked_stage_prevents_any_operation(tmp_path):
    root, database = _fixture(tmp_path)
    (root / "keep").rmdir()
    (root / "keep").symlink_to(root / "holding", target_is_directory=True)
    with pytest.raises(RuntimeError, match="Unsafe"):
        _run(root, database)
    assert INTENTS_KEY not in _state(database)
