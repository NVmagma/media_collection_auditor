"""Fresh-process SQLite lifecycle rehearsal never persists hypothetical moves."""

import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime

import pytest

from app.sqlite_lifecycle_restart_rehearsal import rehearse_cycles_from_snapshot
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS

KEY = "DISPOSABLE/Movie"


def _artifacts(tmp_path):
    source, backup, database = (
        tmp_path / name for name in ("state.json", "backup.json", "state.db")
    )
    state = {section: {} for section in SECTIONS}
    state["first_seen"][KEY] = "2024-01-01T00:00:00"
    source.write_text(json.dumps(state))
    backup.write_bytes(source.read_bytes())
    write_offline_snapshot(state, database)
    return source, backup, database


def _run_fresh_process(source, backup, database):
    code = """
import json, sys
from datetime import datetime
from app.sqlite_lifecycle_restart_rehearsal import rehearse_cycles_from_snapshot
result = rehearse_cycles_from_snapshot(
    *sys.argv[1:],
    media_key="DISPOSABLE/Movie", initial_stage="Waiting",
    cycles=[
        {"now": datetime(2024, 1, 9), "wait_days": 7, "signals": {}},
        {"now": datetime(2024, 1, 17), "wait_days": 7, "signals": {}},
        {"now": datetime(2024, 1, 25), "wait_days": 7, "signals": {}},
    ],
)
print(json.dumps(result))
"""
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", code, str(source), str(backup), str(database)],
        cwd=root, env=env, check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout)


def test_restart_rehearsal_does_not_persist_simulated_moves(tmp_path):
    source, backup, database = _artifacts(tmp_path)
    original = [p.read_bytes() for p in (source, backup, database)]
    first = _run_fresh_process(source, backup, database)
    second = _run_fresh_process(source, backup, database)
    assert first == second
    assert [step["decision"] for step in first["history"]] == [
        "hold", "to_removal", "delete_candidate",
    ]
    assert first["final_stage"] == "Removal"
    assert first["simulated_state"]["in_removal"][KEY] == "2024-01-17T00:00:00"
    assert first["persisted_state_unchanged"] is True
    assert first["authorization"] == "not_authorized"
    assert first["persistence"] == "none"
    assert first["production_activation"] == "disabled"
    assert [p.read_bytes() for p in (source, backup, database)] == original


def test_missing_protection_never_advances_after_restart(tmp_path):
    source, backup, database = _artifacts(tmp_path)
    result = rehearse_cycles_from_snapshot(
        source, backup, database, media_key=KEY, initial_stage="Waiting",
        cycles=[{"now": datetime(2024, 1, 20),
                 "wait_days": 7, "signals": None}],
    )
    assert result["final_stage"] == "Waiting"
    assert result["history"][0]["decision"] == "unknown"


def test_backup_mismatch_fails_before_simulation(tmp_path):
    source, backup, database = _artifacts(tmp_path)
    backup.write_text("{}")
    with pytest.raises(RuntimeError):
        rehearse_cycles_from_snapshot(
            source, backup, database, media_key=KEY,
            initial_stage="Waiting", cycles=[],
        )
