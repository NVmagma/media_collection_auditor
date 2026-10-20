"""Actual JSON load/save/restart compatibility, restricted to disposable copies."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest
from tests.test_sqlite_disposable_copy_intent import lab
from tests.test_sqlite_disposable_rollback import advance, NAME
from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_disposable_rollback import export_disposable_rollback_candidate
from app.state_store import GuardedSQLiteStateStore

CHILD = r'''
import hashlib
import json
import requests
import sys

def no_network(*args, **kwargs):
    raise AssertionError("Network access forbidden in rollback rehearsal")
requests.sessions.Session.request = no_network
import collection_auditor as auditor
state = auditor.load_state()
if sys.argv[1] == "save":
    auditor.save_state(state)
    assert auditor.load_state() == state
encoded = json.dumps(state, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
print("PARITY=" + hashlib.sha256(encoded.encode("ascii")).hexdigest())
'''


def child(root, path, mode):
    repo = Path(__file__).resolve().parents[1]
    # Do not inherit service credentials, production paths or user config.
    env = {"PYTHONPATH": str(repo / "app"), "STATE_FILE": str(path),
           "DRY_RUN": "true", "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run([sys.executable, "-B", "-c", CHILD, mode],
                            cwd=root, env=env, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return next(line for line in result.stdout.splitlines() if line.startswith("PARITY="))


@pytest.mark.parametrize("with_tv", [False, True])
def test_export_survives_actual_json_save_and_fresh_process_restart(lab, with_tv):
    baseline = GuardedSQLiteStateStore(lab / "state.db").load_with_revision()[0]
    original = lab / "auditor_state.json"
    original.write_text(json.dumps(baseline))
    original_bytes = original.read_bytes()
    advance(lab)
    if with_tv:
        session = RevisionedAuditSession(GuardedSQLiteStateStore(lab / "state.db"))
        session.state["first_seen"]["TV/Waiting Show"] = "2024-01-01T00:00:00"
        session.state["keep_seen"]["TV/Kept Show"] = "2024-02-01T00:00:00"
        session.state["in_removal"]["TV/Leaving Show"] = "2024-03-01T00:00:00"
        session.state["arr_sync_pending"]["TV/Kept Show"] = {
            "stage": "keep", "root": "/fixture/tv_keep", "monitored": True,
            "service": "sonarr", "title_id": 99, "unknown_retry_metadata": {"attempts": 2}}
        session.checkpoint()
    expected, _ = GuardedSQLiteStateStore(lab / "state.db").load_with_revision()
    database_bytes = (lab / "state.db").read_bytes()
    export_disposable_rollback_candidate(root=lab, candidate_name=NAME)
    candidate_bytes = (lab / NAME).read_bytes()
    restart_dir = lab / "json-restart"
    restart_dir.mkdir()
    restored_copy = restart_dir / "fixture_state.json"
    restored_copy.write_bytes(candidate_bytes)
    encoded = json.dumps(expected, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    parity = "PARITY=" + hashlib.sha256(encoded.encode("ascii")).hexdigest()
    assert child(restart_dir, restored_copy, "load") == parity
    assert child(restart_dir, restored_copy, "save") == parity
    assert child(restart_dir, restored_copy, "load") == parity
    assert json.loads(restored_copy.read_bytes()) == expected
    assert original.read_bytes() == original_bytes
    assert (lab / "state.db").read_bytes() == database_bytes
    assert (lab / NAME).read_bytes() == candidate_bytes
