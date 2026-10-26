"""Separate processes contend on the real JSON writer/migration lock."""
from pathlib import Path
import subprocess
import sys

from app.sqlite_lock import audit_run_lock, migration_lock

CHILD = r'''
import sys
import requests
requests.sessions.Session.request = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("No network"))
if sys.argv[1] == "save":
    import collection_auditor as auditor
    action = lambda: auditor.save_state(auditor.load_state())
else:
    from app.sqlite_migration import create_offline_migration_snapshot
    from pathlib import Path
    root = Path(sys.argv[2])
    action = lambda: create_offline_migration_snapshot(root / "state.json", root / "backup.json", root / "snapshot.db")
try:
    action()
except RuntimeError:
    print("BLOCKED")
    raise SystemExit(2)
print("COMPLETED")
'''


def child(root, action):
    repo = Path(__file__).resolve().parents[1]
    env = {"PYTHONPATH": str(repo) + ":" + str(repo / "app"),
           "STATE_FILE": str(root / "state.json"), "DRY_RUN": "true",
           "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, "-B", "-c", CHILD, action, str(root)],
                          cwd=root, env=env, capture_output=True, text=True, timeout=30)


def test_actual_json_save_is_blocked_by_other_process_migration(tmp_path):
    source = tmp_path / "state.json"
    source.write_text('{"first_seen":{"Movie":"2024-01-01T00:00:00"}}')
    before = source.read_bytes()
    lock_path = tmp_path / "state.json.migration.lock"
    with migration_lock(source):
        identity = lock_path.stat().st_ino
        result = child(tmp_path, "save")
        assert result.returncode == 2 and "BLOCKED" in result.stdout
        assert source.read_bytes() == before
        assert not list(tmp_path.glob(".auditor_state_*.tmp"))
    result = child(tmp_path, "save")
    assert result.returncode == 0 and "COMPLETED" in result.stdout
    assert lock_path.stat().st_ino == identity


def test_actual_migration_is_blocked_by_other_process_audit(tmp_path):
    source = tmp_path / "state.json"
    source.write_text("{}")
    with audit_run_lock(source):
        result = child(tmp_path, "migrate")
        assert result.returncode == 2 and "BLOCKED" in result.stdout
        assert not (tmp_path / "backup.json").exists()
        assert not (tmp_path / "snapshot.db").exists()
    result = child(tmp_path, "migrate")
    assert result.returncode == 0 and "COMPLETED" in result.stdout
    assert source.read_bytes() == (tmp_path / "backup.json").read_bytes()
