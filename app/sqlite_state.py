"""Read-only SQLite state prototype.

This module deliberately does not migrate JSON, create databases, or change the
auditor's authoritative JSON state. Schema activation is a later, tested step.
"""

from __future__ import annotations

import datetime
import json
import sqlite3
from pathlib import Path
from typing import Any

SECTIONS = ("first_seen", "queued", "in_removal", "keep_seen", "arr_sync_pending")
SCHEMA_VERSION = 2

# Preserve state keys and values exactly; do not reinterpret naive local timestamps.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS extra_state (\n    key TEXT PRIMARY KEY,\n    value_json TEXT NOT NULL\n);\nCREATE TABLE IF NOT EXISTS state_entries (
    section TEXT NOT NULL,
    media_key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    PRIMARY KEY (section, media_key)
);
"""


def validate_snapshot(state: dict[str, dict[str, Any]]) -> None:
    """Apply the auditor's existing lifecycle and Arr retry invariants.

    This is intentionally independent of the production JSON loader; the
    auditor continues to use that loader until migration is explicitly enabled.
    """
    if not isinstance(state, dict) or any(
        section not in state or not isinstance(state[section], dict)
        for section in SECTIONS
    ):
        raise RuntimeError("SQLite snapshot has missing or invalid state sections")
    now = datetime.datetime.now()
    for section in SECTIONS[:-1]:
        for key, timestamp in state[section].items():
            if not isinstance(key, str) or not key or not isinstance(timestamp, str):
                raise RuntimeError(f"Invalid {section} state entry")
            try:
                parsed = datetime.datetime.fromisoformat(timestamp)
            except ValueError as exc:
                raise RuntimeError(f"Invalid {section} timestamp") from exc
            if parsed.tzinfo is not None or parsed > now:
                raise RuntimeError(f"Unsafe {section} timestamp")
    for key, entry in state["arr_sync_pending"].items():
        if (not isinstance(key, str) or not key or not isinstance(entry, dict)
                or entry.get("stage") not in ("holding", "keep", "removal")
                or not isinstance(entry.get("root"), str) or not entry["root"]
                or (entry.get("monitored") is not None
                    and type(entry["monitored"]) is not bool)):
            raise RuntimeError("Invalid Arr retry entry")


def read_snapshot(database_path: str | Path) -> dict[str, dict[str, Any]]:
    """Read an existing SQLite snapshot without creating or modifying it.

    Fail closed if the database is missing, invalid, or incomplete. This is
    inspection only; it is not used for audit decisions.
    """
    path = Path(database_path)
    if not path.is_file():
        raise RuntimeError(f"SQLite snapshot is unavailable: {path}")
    try:
        connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
        try:
            connection.execute("BEGIN")  # One coherent read, including optional live integrity.
            version_row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'schema_version'"
            ).fetchone()
            if version_row is None or version_row[0] != str(SCHEMA_VERSION):
                raise RuntimeError("SQLite snapshot schema version is missing or unsupported")
            complete_row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'snapshot_complete'"
            ).fetchone()
            if complete_row != ("1",):
                raise RuntimeError("SQLite snapshot is incomplete; refusing to use it")
            rows = connection.execute(
                "SELECT section, media_key, value_json FROM state_entries"
            ).fetchall()
            result: dict[str, dict[str, Any]] = {
                section: {} for section in SECTIONS
            }
            for section, media_key, value_json in rows:
                if section not in result or not isinstance(media_key, str) or not media_key:
                    raise RuntimeError("SQLite snapshot contains an invalid state key")
                value = json.loads(value_json)
                if section == "arr_sync_pending":
                    if not isinstance(value, dict):
                        raise RuntimeError("SQLite snapshot contains invalid Arr retry data")
                elif not isinstance(value, str):
                    raise RuntimeError("SQLite snapshot contains an invalid lifecycle timestamp")
                result[section][media_key] = value
            for key, value_json in connection.execute(
                "SELECT key, value_json FROM extra_state"
            ):
                if not isinstance(key, str) or not key or key in result:
                    raise RuntimeError("SQLite snapshot contains an invalid extra state key")
                result[key] = json.loads(value_json)
            validate_snapshot(result)
            from app.sqlite_live_integrity import KEY,verify
            integrity=connection.execute('SELECT value FROM metadata WHERE key=?',(KEY,)).fetchone()
            if integrity is not None:
                row=connection.execute("SELECT value FROM metadata WHERE key='state_revision'").fetchone()
                revision=0 if row is None else int(row[0])
                if revision<0 or (row is not None and str(revision)!=row[0]):
                    raise RuntimeError('Invalid live state revision')
                verify(integrity[0],result,revision)
            return result
        finally:
            connection.close()
    except (sqlite3.Error, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"SQLite snapshot is unreadable: {path}") from exc
