"""Independent-process SQLite persistence checks on disposable databases."""

import json
import os
from pathlib import Path
import subprocess
import sys

from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.sqlite_store import SQLiteStateStore


def _state():
    return {section: {} for section in SECTIONS}


def test_sqlite_update_survives_process_restart(tmp_path):
    database = tmp_path / "tracking.db"
    write_offline_snapshot(_state(), database)
    changed = _state()
    changed["first_seen"]["Movie"] = "2024-01-01T01:02:03"
    changed["keep_seen"]["Series/Show"] = "2024-02-01T01:02:03"
    changed["arr_sync_pending"]["Movie"] = {
        "stage": "keep", "root": "/media/Movies_keep", "monitored": False,
    }
    changed["legacy"] = {"nested": [1, None, True]}
    SQLiteStateStore(database).save(changed)

    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    code = (
        "import json,sys; from app.sqlite_store import SQLiteStateStore; "
        "print(json.dumps(SQLiteStateStore(sys.argv[1]).load()))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(database)],
        cwd=root, env=env, capture_output=True, text=True, check=True,
    )
    assert json.loads(result.stdout) == changed
    assert SQLiteStateStore(database).load() == changed
