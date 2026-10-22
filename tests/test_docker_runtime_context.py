"""Run Python from Docker COPY inputs only; no Docker build or repository imports."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def recipe():
    # Git tracks Dockerfile and dockerfile separately. Case-insensitive macOS
    # checkouts cannot represent both: use the exact indexed uppercase recipe.
    # The pinned Python lab image lacks git; Linux can read the real file.
    if shutil.which("git") and (ROOT / ".git").exists():
        result = subprocess.run(["git", "show", ":Dockerfile"], cwd=ROOT,
                                capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout
    return (ROOT / "Dockerfile").read_text()


def context(tmp_path):
    for line in recipe().splitlines():
        parts = shlex.split(line)
        if (len(parts) == 3 and parts[0] == "COPY" and parts[1].startswith("app/")
                and parts[1].endswith(".py") and parts[2] == "."):
            shutil.copyfile(ROOT / parts[1], tmp_path / Path(parts[1]).name)
    return tmp_path


def probe(runtime, raw):
    source = runtime / "fixture_state.json"
    source.write_text(raw)
    env = {"PYTHONPATH": str(runtime), "STATE_FILE": str(source),
           "WEB_SESSION_SECRET": "disposable-runtime-context-secret",
           "DRY_RUN": "true", "PYTHONDONTWRITEBYTECODE": "1"}
    child = '''
import requests
requests.sessions.Session.request = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("No network"))
import sqlite_lock, collection_auditor, web
from dashboard_tracking_snapshot import read_json_dashboard_snapshot
try:
    state = web.load_state()
except RuntimeError:
    print("TRACKING_ERROR_VISIBLE")
else:
    assert state == {"first_seen": {"Example": "2024-01-01T00:00:00"}}
    import os
    os.environ["INTEGRATION_API_TOKEN"] = "disposable_runtime_integration_token_0123456789"
    client = web.app.test_client()
    assert client.get("/api/v1/summary").status_code == 401
    response = client.get("/api/v1/summary", headers={
        "Authorization": "Bearer " + os.environ["INTEGRATION_API_TOKEN"]})
    assert response.status_code == 200
    assert response.json["tracking_counts"]["waiting"] == 1
    audit = client.get("/api/v1/audit-status", headers={
        "Authorization": "Bearer " + os.environ["INTEGRATION_API_TOKEN"]})
    assert audit.status_code == 200
    assert audit.json["source"] == "coordinator_snapshot"
    assert audit.json["freshness_verified"] is False
    print("RUNTIME_OK")
'''
    return subprocess.run([sys.executable, "-B", "-c", child], cwd=runtime, env=env,
                          capture_output=True, text=True, timeout=30)


def test_shipped_runtime_can_import_and_read_dashboard_snapshot(tmp_path):
    runtime = context(tmp_path)
    result = probe(runtime, json.dumps({"first_seen": {"Example": "2024-01-01T00:00:00"}}))
    assert result.returncode == 0, result.stderr
    assert "RUNTIME_OK" in result.stdout


def test_shipped_runtime_rejects_corrupt_tracking(tmp_path):
    result = probe(context(tmp_path), '{"first_seen":[]}')
    assert result.returncode == 0, result.stderr
    assert "TRACKING_ERROR_VISIBLE" in result.stdout


def test_smoke_context_exposes_missing_runtime_dependency(tmp_path):
    runtime = context(tmp_path)
    (runtime / "dashboard_tracking_snapshot.py").unlink()
    result = probe(runtime, "{}")
    assert result.returncode != 0
    assert "dashboard_tracking_snapshot" in result.stderr


def test_smoke_context_exposes_missing_backend_gate_dependency(tmp_path):
    runtime = context(tmp_path)
    (runtime / "sqlite_backend_gate.py").unlink()
    result = probe(runtime, "{}")
    assert result.returncode != 0
    assert "sqlite_backend_gate" in result.stderr
