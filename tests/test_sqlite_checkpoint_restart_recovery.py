"""Durable SQLite checkpoint/restart tests using disposable databases only.

No production backend selection, Jellyfin calls or media filesystem operations.
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


def _database(tmp_path):
    path = tmp_path / "state.db"
    state = {section: {} for section in SECTIONS}
    state["first_seen"]["DISPOSABLE/Movie"] = "2024-01-01T00:00:00"
    write_offline_snapshot(state, path)
    return path


def _fresh_process(path):
    code = """
import json, sys
from app.sqlite_audit_session import RevisionedAuditSession
from app.state_store import GuardedSQLiteStateStore
session = RevisionedAuditSession(GuardedSQLiteStateStore(sys.argv[1]))
state, revision = session.read_verified_snapshot()
print(json.dumps({"revision": revision, "state": state}))
"""
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", code, str(path)],
        cwd=root, env=env, capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


def test_checkpoint_survives_fresh_process_and_rejects_stale_writer(tmp_path):
    path = _database(tmp_path)
    store = GuardedSQLiteStateStore(path)
    first = RevisionedAuditSession(store)
    stale = RevisionedAuditSession(store)
    first.state["queued"]["DISPOSABLE/Other"] = "2024-01-09T00:00:00"
    first.checkpoint()

    restarted = _fresh_process(path)
    assert restarted["revision"] == 1
    assert restarted["state"] == first.state

    stale.state["in_removal"]["DISPOSABLE/Movie"] = "2024-01-10T00:00:00"
    with pytest.raises(RuntimeError, match="Stale SQLite state revision"):
        stale.checkpoint()
    with pytest.raises(RuntimeError, match="reopen required"):
        stale.checkpoint()
    assert _fresh_process(path) == restarted


def test_pending_intent_survives_restart_and_blocks_new_operations(tmp_path):
    path = _database(tmp_path)
    session = RevisionedAuditSession(GuardedSQLiteStateStore(path))
    coordinator = SQLiteOperationCoordinator(session)
    coordinator.begin("disposable-operation", "arr_sync", {
        "media_key": "DISPOSABLE/Movie",
        "description": "No external operation performed",
    })

    restarted = _fresh_process(path)
    assert restarted["revision"] == 1
    assert restarted["state"][INTENTS_KEY]["phase"] == "intent_recorded"

    fresh = RevisionedAuditSession(GuardedSQLiteStateStore(path))
    with pytest.raises(RuntimeError, match="Unresolved SQLite operation"):
        SQLiteOperationCoordinator(fresh).begin(
            "second-operation", "arr_sync", {"media_key": "DISPOSABLE/Other"}
        )
    assert _fresh_process(path) == restarted


def test_applied_intent_still_requires_reconciliation_after_restart(tmp_path):
    path = _database(tmp_path)
    session = RevisionedAuditSession(GuardedSQLiteStateStore(path))
    coordinator = SQLiteOperationCoordinator(session)
    coordinator.begin("disposable-operation", "arr_sync", {
        "media_key": "DISPOSABLE/Movie"
    })
    coordinator.mark_applied("disposable-operation")

    restarted = _fresh_process(path)
    assert restarted["revision"] == 2
    assert restarted["state"][INTENTS_KEY]["phase"] == "applied_pending_reconciliation"

    fresh = RevisionedAuditSession(GuardedSQLiteStateStore(path))
    with pytest.raises(RuntimeError, match="verification|reconciliation|refus|trusted"):
        SQLiteOperationCoordinator(fresh).reconcile(
            "disposable-operation", {"caller_claim": "success"}
        )
    assert _fresh_process(path) == restarted


def test_missing_database_cannot_be_recreated_after_restart(tmp_path):
    path = tmp_path / "missing.db"
    code = """
import sys
from app.sqlite_audit_session import RevisionedAuditSession
from app.state_store import GuardedSQLiteStateStore
RevisionedAuditSession(GuardedSQLiteStateStore(sys.argv[1]))
"""
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", code, str(path)],
        cwd=root, env=env, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert not path.exists()
