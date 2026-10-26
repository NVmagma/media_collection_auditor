"""Synthetic end-to-end migration/advanced-state rollback, never live cutover."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_disposable_rollback import (export_disposable_rollback_candidate,
                                          inspect_disposable_rollback_candidate)
from app.sqlite_migration import create_offline_migration_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore

_CHILD = r'''
import hashlib, json, requests, sys
from pathlib import Path

def forbid_network(*args, **kwargs):
    raise RuntimeError("Network forbidden in disposable rehearsal")
requests.sessions.Session.request = forbid_network
import collection_auditor as auditor
state = auditor.load_state()
if sys.argv[1] == "save":
    auditor.save_state(state)
    if auditor.load_state() != state:
        raise RuntimeError("JSON save parity failed")
payload = json.dumps(state, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
print("PARITY=" + hashlib.sha256(payload.encode("ascii")).hexdigest())
'''


def _json_restart(root, candidate, expected):
    directory = root / "json-restart"
    directory.mkdir(mode=0o700)
    state_path = directory / "fixture_state.json"
    with state_path.open("xb") as output:
        output.write(candidate.read_bytes())
        output.flush()
        os.fsync(output.fileno())
    app_dir = Path(__file__).resolve().parent
    env = {"PYTHONPATH": str(app_dir), "STATE_FILE": str(state_path),
           "DRY_RUN": "true", "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONIOENCODING": "utf-8"}
    payload = json.dumps(expected, ensure_ascii=True, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("ascii")
    parity = "PARITY=" + hashlib.sha256(payload).hexdigest()
    for mode in ("load", "save", "load"):
        result = subprocess.run([sys.executable, "-B", "-c", _CHILD, mode],
                                cwd=directory, env=env, capture_output=True,
                                text=True, timeout=30)
        if result.returncode != 0 or parity not in result.stdout.splitlines():
            raise RuntimeError("Disposable JSON restart parity failed")
    if json.loads(state_path.read_bytes()) != expected:
        raise RuntimeError("Disposable JSON tracking history mismatch")


def rehearse_disposable_cutover(*, root):
    """Create a NEW private fixture root; preserve every artifact on failure.

    No existing database, JSON state, media or service configuration is accepted.
    The caller supplies only a never-before-used absolute fixture directory.
    """
    root = Path(root)
    if not root.is_absolute() or root.resolve() != root or not root.parent.is_dir():
        raise ValueError("New absolute disposable fixture root required")
    root.mkdir(mode=0o700)  # Exclusive: never reuse or overwrite a prior lab.
    (root / ".sqlite_disposable_rehearsal").write_text("DISPOSABLE ONLY\n")
    source, backup, database = root / "original.json", root / "original.backup.json", root / "state.db"
    initial = {section: {} for section in SECTIONS}
    initial["first_seen"] = {"Fixture Movie": "2024-01-01T00:00:00", "TV/Fixture Show": "2024-01-01T00:00:00"}
    initial["legacy"] = {"unicode": "caf\u00e9", "nested": [1, False, None]}
    with source.open("xb") as output:
        output.write(json.dumps(initial, ensure_ascii=True).encode("ascii"))
        output.flush()
        os.fsync(output.fileno())
    original_bytes = source.read_bytes()
    create_offline_migration_snapshot(source, backup, database)
    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    if session.state != initial:
        raise RuntimeError("Disposable migration parity failed")
    session.state["queued"]["Fixture Movie"] = session.state["first_seen"].pop("Fixture Movie")
    session.state["keep_seen"]["TV/Fixture Show"] = session.state["first_seen"].pop("TV/Fixture Show")
    for key, stage, service, identity in (("Fixture Movie", "holding", "radarr", 1),
                                          ("TV/Fixture Show", "keep", "sonarr", 2)):
        session.state["arr_sync_pending"][key] = {
            "stage": stage, "root": "/synthetic/" + stage, "monitored": False,
            "service": service, "title_id": identity, "retry_metadata": {"attempts": 1}}
    session.checkpoint()
    export_disposable_rollback_candidate(root=root, candidate_name="rollback-candidate-earlier.json")
    session.state["legacy"]["newer_history"] = "second checkpoint"
    session.checkpoint()
    if inspect_disposable_rollback_candidate(root=root, candidate_name="rollback-candidate-earlier.json")["status"] != "blocked":
        raise RuntimeError("Stale rollback candidate accepted")
    candidate = root / "rollback-candidate-current.json"
    report = export_disposable_rollback_candidate(root=root, candidate_name=candidate.name)
    expected, revision = session.read_verified_snapshot()
    database_bytes, candidate_bytes = database.read_bytes(), candidate.read_bytes()
    _json_restart(root, candidate, expected)
    session.read_verified_snapshot()
    if (database.read_bytes() != database_bytes or candidate.read_bytes() != candidate_bytes
            or source.read_bytes() != original_bytes or backup.read_bytes() != original_bytes):
        raise RuntimeError("Disposable rehearsal changed retained history")
    if report["revision"] != revision:
        raise RuntimeError("Disposable rehearsal revision mismatch")
    return {"status": "rehearsal_passed_advisory_only", "revision": revision,
            "migration_parity": True, "stale_candidate_blocked": True,
            "advanced_history_preserved": True, "json_restart_parity": True,
            "original_backup_unchanged": True, "synthetic_data_only": True,
            "authorization": "not_authorized", "production_activation": "disabled",
            "production_restore_performed": False, "media_actions_performed": False}
