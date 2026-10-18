"""Offline, backup-first preparation for a future SQLite migration.

This module never activates SQLite or changes the auditor's JSON state.
Stop the auditor before using it; concurrent writes are not supported yet.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from app.sqlite_state import SECTIONS, validate_snapshot


def prepare_json_backup(source: str | Path, backup: str | Path) -> dict:
    """Validate source and create a durable, exclusive backup.

    Refuse to overwrite any backup or to proceed if source changes while
    copying. The caller must ensure the auditor is stopped.
    """
    source, backup = Path(source), Path(backup)
    if source.resolve() == backup.resolve():
        raise RuntimeError("Backup must not overwrite the source state")
    if not source.is_file():
        raise RuntimeError("Source JSON state is missing; refusing migration")
    if backup.exists():
        raise RuntimeError("Backup already exists; refusing to overwrite")
    if not backup.parent.is_dir():
        raise RuntimeError("Backup directory does not exist")
    try:
        original = source.read_bytes()
        state = json.loads(original)
        if not isinstance(state, dict):
            raise RuntimeError("Source JSON state is not an object")
        normalized = dict(state)
        for section in SECTIONS:
            normalized.setdefault(section, {})
        validate_snapshot(normalized)
        # Exclusive creation prevents accidental replacement of an earlier backup.
        with backup.open("xb") as output:
            output.write(original)
            output.flush()
            os.fsync(output.fileno())
        if source.read_bytes() != original or backup.read_bytes() != original:
            raise RuntimeError("Source changed during backup; refusing migration")
        if os.name == "posix":
            fd = os.open(str(backup.parent), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        return normalized
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        raise RuntimeError("Could not validate or back up JSON state") from exc
