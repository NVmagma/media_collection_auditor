"""Experimental SQLite state store for isolated tests only.

Never selected by production auditor. Requires an existing, completed schema-v2
snapshot; missing or damaged databases are never initialized as empty state.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

from app.sqlite_state import SCHEMA_VERSION, SECTIONS, read_snapshot, validate_snapshot


class SQLiteStateStore:
    """Transactional whole-snapshot updates for an explicitly supplied test DB."""

    def __init__(self, database: str | Path):
        self.database = Path(database)

    def load(self) -> dict[str, Any]:
        return read_snapshot(self.database)

    def save(self, state: dict[str, Any]) -> None:
        validate_snapshot(state)
        # Preflight before opening writable: never initialize a missing or
        # incomplete database, even if the requested state looks valid.
        read_snapshot(self.database)
        try:
            connection = sqlite3.connect(
                f"file:{self.database.resolve().as_posix()}?mode=rw",
                uri=True, timeout=5,
            )
            try:
                connection.execute("PRAGMA synchronous=FULL")
                connection.execute("BEGIN IMMEDIATE")
                # Recheck under the writer lock to reject a changed schema or
                # incomplete snapshot between preflight and the transaction.
                version = connection.execute(
                    "SELECT value FROM metadata WHERE key='schema_version'"
                ).fetchone()
                complete = connection.execute(
                    "SELECT value FROM metadata WHERE key='snapshot_complete'"
                ).fetchone()
                if version != (str(SCHEMA_VERSION),) or complete != ("1",):
                    raise RuntimeError("SQLite state changed or is incomplete")
                connection.execute("DELETE FROM state_entries")
                connection.execute("DELETE FROM extra_state")
                for section in SECTIONS:
                    for key, value in state[section].items():
                        connection.execute(
                            "INSERT INTO state_entries (section, media_key, value_json) "
                            "VALUES (?, ?, ?)",
                            (section, key, json.dumps(value, ensure_ascii=False, allow_nan=False)),
                        )
                for key, value in state.items():
                    if key not in SECTIONS:
                        connection.execute(
                            "INSERT INTO extra_state (key, value_json) VALUES (?, ?)",
                            (key, json.dumps(value, ensure_ascii=False, allow_nan=False)),
                        )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()
        except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
            raise RuntimeError("SQLite state write failed; refusing to continue") from exc
        if read_snapshot(self.database) != state:
            raise RuntimeError("SQLite state verification failed after commit")
