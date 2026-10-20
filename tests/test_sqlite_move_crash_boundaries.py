"""Crash-boundary rehearsals using disposable SQLite state and directories.

Only the test itself renames media. Production remains JSON-only.
"""

from pathlib import Path

import pytest

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_operation_coordinator import INTENTS_KEY, SQLiteOperationCoordinator
from app.sqlite_persisted_recovery_review import review_persisted_move
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore

STAGES = ("transient", "holding", "removal", "keep")
KEY = "DISPOSABLE/Movie"
OP = "disposable-crash-move"


def _setup(tmp_path):
    paths = {}
    for stage in STAGES:
        root = tmp_path / stage
        root.mkdir()
        paths[stage] = str(root / "Movie")
    source = Path(paths["transient"])
    source.mkdir()
    (source / "marker").write_text("unchanged")
    state = {section: {} for section in SECTIONS}
    state["first_seen"][KEY] = "2024-01-01T00:00:00"
    database = tmp_path / "state.db"
    write_offline_snapshot(state, database)
    return database, paths


def _session(database):
    return RevisionedAuditSession(GuardedSQLiteStateStore(database))


def _begin(session, paths):
    SQLiteOperationCoordinator(session).begin_move_with_evidence(
        OP, {"media_key": KEY, "source": paths["transient"],
             "destination": paths["holding"]}
    )


def _review(database, paths):
    return review_persisted_move(
        _session(database), operation_id=OP, media_key=KEY,
        stage_paths=paths, source_stage="transient",
        destination_stage="holding",
    )


def _safe(result):
    assert result["authorization"] == "not_authorized"
    assert result["checkpoint_allowed"] is False
    assert result["intent_clearance"] == "blocked"
    assert result["replay_allowed"] is False


def test_before_intent_checkpoint_failure_prevents_move(tmp_path, monkeypatch):
    database, paths = _setup(tmp_path)
    before = database.read_bytes()
    session = _session(database)

    def fail_checkpoint():
        raise RuntimeError("injected before persistence")

    monkeypatch.setattr(session, "checkpoint", fail_checkpoint)
    with pytest.raises(RuntimeError, match="injected"):
        _begin(session, paths)
    assert database.read_bytes() == before
    assert Path(paths["transient"]).is_dir()
    assert not Path(paths["holding"]).exists()
    _safe(_review(database, paths))
    assert _review(database, paths)["reason"] == "persisted_intent_missing"


def test_crash_after_intent_before_move_preserves_pending_intent(tmp_path):
    database, paths = _setup(tmp_path)
    _begin(_session(database), paths)
    before = database.read_bytes()
    fresh = _session(database)
    assert fresh.state[INTENTS_KEY]["phase"] == "intent_recorded"
    result = _review(database, paths)
    _safe(result)
    assert result["status"] == "blocked"
    assert database.read_bytes() == before
    assert Path(paths["transient"]).is_dir()
    with pytest.raises(RuntimeError, match="Unresolved SQLite operation"):
        SQLiteOperationCoordinator(fresh).begin("another", "arr_sync", {"media_key": KEY})


def test_crash_after_disposable_move_never_replays_or_clears(tmp_path):
    database, paths = _setup(tmp_path)
    _begin(_session(database), paths)
    Path(paths["transient"]).rename(paths["holding"])
    before = database.read_bytes()
    first = _review(database, paths)
    second = _review(database, paths)
    _safe(first)
    assert first == second
    assert first["status"] == "advisory"
    assert database.read_bytes() == before
    assert (Path(paths["holding"]) / "marker").read_text() == "unchanged"
    assert _session(database).state[INTENTS_KEY]["phase"] == "intent_recorded"


class _CommittedButUnconfirmedStore:
    """Simulate failure after SQLite commits but before checkpoint readback."""

    def __init__(self, database):
        self._store = GuardedSQLiteStateStore(database)
        self.fail_once = True

    def load_with_revision(self):
        if not self.fail_once:
            raise RuntimeError("injected readback failure")
        return self._store.load_with_revision()

    def save_if_revision(self, state, revision):
        self._store.save_if_revision(state, revision)
        self.fail_once = False


def test_uncertain_checkpoint_quarantines_session_and_requires_reopen(tmp_path):
    database, paths = _setup(tmp_path)
    store = _CommittedButUnconfirmedStore(database)
    session = RevisionedAuditSession(store)
    with pytest.raises(RuntimeError, match="injected readback failure"):
        _begin(session, paths)
    with pytest.raises(RuntimeError, match="reopen required"):
        session.read_verified_snapshot()
    with pytest.raises(RuntimeError, match="reopen required"):
        session.checkpoint()
    fresh = _session(database)
    assert fresh.state[INTENTS_KEY]["phase"] == "intent_recorded"
    result = _review(database, paths)
    _safe(result)
    assert result["status"] == "blocked"
    assert Path(paths["transient"]).is_dir()
    assert not Path(paths["holding"]).exists()
