import json
"""Offline, backup-first preparation for a future SQLite migration.

This module never activates SQLite or changes the auditor's JSON state.
Stop the auditor before using it; concurrent writes are not supported yet.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.sqlite_json import parse_unique_json
from app.sqlite_state import SECTIONS, validate_snapshot
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_lock import migration_lock


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
        state = parse_unique_json(original)
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


def create_offline_migration_snapshot(
    source: str | Path, backup: str | Path, destination: str | Path
) -> None:
    """Prepare a backed-up SQLite copy, leaving JSON authoritative.

    Unknown top-level fields are not representable in schema v1. Refuse to
    convert rather than silently discarding potentially important history.
    No automatic retry or activation is attempted on partial failures.
    """
    source, backup, destination = Path(source), Path(backup), Path(destination)
    if len({source.resolve(), backup.resolve(), destination.resolve()}) != 3:
        raise RuntimeError("Source, backup, and database paths must be distinct")
    if destination.exists():
        raise RuntimeError("SQLite destination already exists")
    with migration_lock(source):
        state = prepare_json_backup(source, backup)
        unknown = set(state).difference(SECTIONS)
        if unknown:
            raise RuntimeError(
                "Unknown historical state sections cannot be converted by schema v1: "
                + ", ".join(sorted(unknown))
            )
        # The source is rechecked after backup and immediately before conversion.
        # Caller must still stop all auditor instances to prevent concurrent writes.
        if source.read_bytes() != backup.read_bytes():
            raise RuntimeError("Source changed after backup; refusing conversion")
        write_offline_snapshot(state, destination)
