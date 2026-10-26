"""Disposable named-volume SQLite persistence rehearsal; never accesses /lab or media."""
from __future__ import annotations

import json
from pathlib import Path
import sys

from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.sqlite_store import SQLiteStateStore

ROOT = Path("/rehearsal")
DATABASE = ROOT / "sqlite-persistence-rehearsal.db"
KEY = "DISPOSABLE/Example"
STAMP = "2024-01-01T00:00:00"


def run(phase: str) -> dict:
    if not ROOT.is_dir() or ROOT.is_symlink():
        raise RuntimeError("Dedicated /rehearsal volume is missing or invalid")
    if ROOT.resolve() != ROOT:
        raise RuntimeError("Unexpected rehearsal path")
    if phase == "prepare":
        if any(ROOT.iterdir()):
            raise RuntimeError("Rehearsal volume must be empty; refusing overwrite")
        state = {section: {} for section in SECTIONS}
        state["first_seen"][KEY] = STAMP
        write_offline_snapshot(state, DATABASE)
        return {"phase": phase, "status": "prepared", "authorization": "not_authorized"}
    if phase not in ("advance", "verify"):
        raise RuntimeError("Unknown phase")
    if not DATABASE.is_file() or DATABASE.is_symlink():
        raise RuntimeError("Expected disposable database missing")
    if {p.name for p in ROOT.iterdir()} != {DATABASE.name}:
        raise RuntimeError("Unexpected files in rehearsal volume")
    store = SQLiteStateStore(DATABASE)
    state, revision = store.load_with_revision()
    if phase == "advance":
        if revision != 0 or state["first_seen"] != {KEY: STAMP} or state["keep_seen"]:
            raise RuntimeError("Unexpected initial state; refusing update")
        state["keep_seen"][KEY] = state["first_seen"].pop(KEY)
        store.save_if_revision(state, revision)
        return {"phase": phase, "status": "advanced", "authorization": "not_authorized"}
    if revision != 1 or state["first_seen"] or state["keep_seen"] != {KEY: STAMP}:
        raise RuntimeError("Keep state not persisted")
    return {"phase": phase, "status": "persisted", "authorization": "not_authorized"}


if __name__ == "__main__":
    try:
        print(json.dumps(run(sys.argv[1] if len(sys.argv) == 2 else "")))
    except (RuntimeError, OSError) as exc:
        print(json.dumps({"status": "blocked", "authorization": "not_authorized",
                          "reason": str(exc)}))
        sys.exit(1)
