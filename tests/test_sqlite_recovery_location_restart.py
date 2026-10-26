"""Fresh-process recovery checks using disposable media and SQLite state.

The only filesystem rename is a test-controlled simulation, never Auditor code.
"""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_operation_coordinator import INTENTS_KEY, SQLiteOperationCoordinator
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore

STAGES = ("transient", "holding", "removal", "keep")


def _setup(tmp_path):
    paths = {}
    for stage in STAGES:
        root = tmp_path / stage
        root.mkdir()
        paths[stage] = str(root / "Movie")
    Path(paths["transient"]).mkdir()
    marker = Path(paths["transient"]) / "sentinel.txt"
    marker.write_text("disposable")
    state = {section: {} for section in SECTIONS}
    state["first_seen"]["DISPOSABLE/Movie"] = "2024-01-01T00:00:00"
    database = tmp_path / "state.db"
    write_offline_snapshot(state, database)
    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    SQLiteOperationCoordinator(session).begin_move_with_evidence(
        "disposable-move",
        {"source": paths["transient"], "destination": paths["holding"]},
    )
    return database, paths


def _restart(database, paths):
    code = """
import json, sys
from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_operation_coordinator import INTENTS_KEY, SQLiteOperationCoordinator
from app.sqlite_recovery_location_review import review_interrupted_move
from app.state_store import GuardedSQLiteStateStore
database, serialized = sys.argv[1:]
paths = json.loads(serialized)
session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
state, revision = session.read_verified_snapshot()
review = review_interrupted_move(
    pending_intent=state[INTENTS_KEY], stage_paths=paths,
    expected_destination="holding",
)
try:
    SQLiteOperationCoordinator(session).reconcile("disposable-move", {})
except RuntimeError:
    reconciliation = "blocked"
else:
    reconciliation = "unexpectedly_allowed"
print(json.dumps({"revision": revision, "review": review,
                  "reconciliation": reconciliation,
                  "intent_phase": state[INTENTS_KEY]["phase"]}))
"""
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", code, str(database), json.dumps(paths)],
        cwd=root, env=env, capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


def _safe(result):
    review = result["review"]
    assert result["revision"] == 1
    assert result["intent_phase"] == "intent_recorded"
    assert result["reconciliation"] == "blocked"
    assert review["authorization"] == "not_authorized"
    assert review["checkpoint_allowed"] is False
    assert review["intent_clearance"] == "blocked"
    assert review["replay_allowed"] is False


def test_restart_with_source_present_blocks_without_mutation(tmp_path):
    database, paths = _setup(tmp_path)
    before = database.read_bytes()
    first = _restart(database, paths)
    second = _restart(database, paths)
    assert first == second
    _safe(first)
    assert first["review"]["reason"] == "destination_mismatch"
    assert database.read_bytes() == before
    assert (Path(paths["transient"]) / "sentinel.txt").read_text() == "disposable"
    assert not Path(paths["holding"]).exists()


def test_restart_after_disposable_rename_never_clears_intent(tmp_path):
    database, paths = _setup(tmp_path)
    Path(paths["transient"]).rename(paths["holding"])
    before = database.read_bytes()
    first = _restart(database, paths)
    second = _restart(database, paths)
    assert first == second
    _safe(first)
    assert first["review"]["status"] == "advisory"
    assert database.read_bytes() == before
    assert (Path(paths["holding"]) / "sentinel.txt").read_text() == "disposable"
    assert not Path(paths["transient"]).exists()


@pytest.mark.parametrize("outcome", ["missing", "duplicate", "symlink"])
def test_restart_ambiguous_or_unsafe_location_blocks(tmp_path, outcome):
    database, paths = _setup(tmp_path)
    source = Path(paths["transient"])
    if outcome == "missing":
        (source / "sentinel.txt").unlink()
        source.rmdir()
    elif outcome == "duplicate":
        Path(paths["holding"]).mkdir()
    else:
        Path(paths["holding"]).symlink_to(source, target_is_directory=True)
    before = database.read_bytes()
    result = _restart(database, paths)
    _safe(result)
    assert result["review"]["status"] == "blocked"
    assert database.read_bytes() == before
