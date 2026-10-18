"""Offline SQLite snapshot writer; never activates the database for audits."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3

from app.sqlite_state import SCHEMA_SQL, SCHEMA_VERSION, SECTIONS, read_snapshot, validate_snapshot


def write_offline_snapshot(state: dict, destination: str | Path) -> None:
    """Create a new SQLite snapshot transactionally, without overwriting files.

    Only use with the auditor stopped and after preserving a verified JSON backup.
    The exclusive placeholder reserves the destination against accidental reuse.
    """
    validate_snapshot(state)
    destination = Path(destination)
    if not destination.parent.is_dir():
        raise RuntimeError("SQLite destination directory does not exist")
    if destination.exists():
        raise RuntimeError("SQLite destination already exists")
    created = False
    try:
        with destination.open("xb"):
            pass
        created = True
        with sqlite3.connect(destination) as connection:
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA synchronous=FULL")
            connection.executescript(SCHEMA_SQL)
            with connection:
                connection.execute(
                    "INSERT INTO metadata (key, value) VALUES (?, ?)",
                    ("schema_version", str(SCHEMA_VERSION)),
                )
                for section in SECTIONS:
                    for key, value in state[section].items():
                        connection.execute(
                            "INSERT INTO state_entries (section, media_key, value_json) "
                            "VALUES (?, ?, ?)",
                            (section, key, json.dumps(value, ensure_ascii=False)),
                        )
                for key, value in state.items():
                    if key not in SECTIONS:
                        connection.execute(
                            "INSERT INTO extra_state (key, value_json) VALUES (?, ?)",
                            (key, json.dumps(value, ensure_ascii=False)),
                        )
                connection.execute(
                    "INSERT INTO metadata (key, value) VALUES (?, ?)",
                    ("snapshot_complete", "1"),
                )
        if read_snapshot(destination) != state:
            raise RuntimeError("SQLite snapshot verification failed")
        if os.name == "posix":
            fd = os.open(destination.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    except Exception as exc:
        # A failed output must not be mistaken for a usable snapshot.
        # Preserve it for investigation rather than risking deletion of
        # another process's output in an unsupported concurrent scenario.
        raise RuntimeError(f"SQLite snapshot creation failed: {destination}") from exc
