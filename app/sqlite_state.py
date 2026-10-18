"""Read-only SQLite state prototype.

This module deliberately does not migrate JSON, create databases, or change the
auditor's authoritative JSON state. Schema activation is a later, tested step.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

# Preserve state keys and values exactly; do not reinterpret naive local timestamps.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS state_entries (
    section TEXT NOT NULL,
    media_key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    PRIMARY KEY (section, media_key)
);
"""


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
            version_row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'schema_version'"
            ).fetchone()
            if version_row is None or version_row[0] != str(SCHEMA_VERSION):
                raise RuntimeError("SQLite snapshot schema version is missing or unsupported")
            rows = connection.execute(
                "SELECT section, media_key, value_json FROM state_entries"
            ).fetchall()
            result: dict[str, dict[str, Any]] = {
                section: {} for section in (
                    "first_seen", "queued", "in_removal", "keep_seen", "arr_sync_pending"
                )
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
            return result
        finally:
            connection.close()
    except (sqlite3.Error, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"SQLite snapshot is unreadable: {path}") from exc
