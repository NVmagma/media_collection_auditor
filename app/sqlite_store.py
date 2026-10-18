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

    def _revision(self) -> int:
        try:
            with sqlite3.connect(
                f"file:{self.database.resolve().as_posix()}?mode=ro", uri=True
            ) as connection:
                row = connection.execute(
                    "SELECT value FROM metadata WHERE key='state_revision'"
                ).fetchone()
            value = 0 if row is None else int(row[0])
            if value < 0 or (row is not None and str(value) != row[0]):
                raise ValueError("Invalid state revision")
            return value
        except (sqlite3.Error, ValueError, OSError) as exc:
            raise RuntimeError("SQLite state revision unavailable") from exc

    def load_with_revision(self) -> tuple[dict[str, Any], int]:
        # Retry if a writer commits between reading the revision and state.
        for _ in range(3):
            before = self._revision()
            state = self.load()
            after = self._revision()
            if before == after:
                return state, after
        raise RuntimeError("SQLite state changed during read")

    def save_if_revision(self, state: dict[str, Any], revision: int) -> None:
        """Atomically reject stale writers; use for concurrent clients."""
        if type(revision) is not int or revision < 0:
            raise RuntimeError("Invalid expected SQLite state revision")
        self._save(state, revision)

    def save(self, state: dict[str, Any]) -> None:
        """Legacy experimental API; unsafe for concurrent read-modify-write."""
        self._save(state, None)

    def _save(self, state: dict[str, Any], expected_revision: int | None) -> None:
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
                revision_row = connection.execute(
                    "SELECT value FROM metadata WHERE key='state_revision'"
                ).fetchone()
                try:
                    current_revision = 0 if revision_row is None else int(revision_row[0])
                    if current_revision < 0 or (revision_row is not None
                            and str(current_revision) != revision_row[0]):
                        raise ValueError("Invalid revision")
                except ValueError as exc:
                    raise RuntimeError("Invalid SQLite state revision") from exc
                if (expected_revision is not None
                        and expected_revision != current_revision):
                    raise RuntimeError("Stale SQLite state revision; refusing overwrite")
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
                connection.execute(
                    "INSERT INTO metadata (key, value) VALUES ('state_revision', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (str(current_revision + 1),),
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
