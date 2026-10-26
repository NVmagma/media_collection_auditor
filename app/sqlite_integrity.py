"""Read-only integrity checks for backed-up offline SQLite snapshots.

Verification never activates SQLite or modifies the JSON source, backup, or DB.
"""

from __future__ import annotations

from pathlib import Path

from app.sqlite_json import parse_unique_json
from app.sqlite_state import SECTIONS, read_snapshot, validate_snapshot


def verify_migration_integrity(
    source: str | Path, backup: str | Path, database: str | Path
) -> None:
    """Fail closed unless source, backup, and SQLite contain identical state.

    Exact source/backup bytes matter; SQLite is compared semantically because
    SQL rows cannot preserve JSON formatting and object-key ordering.
    """
    source, backup, database = Path(source), Path(backup), Path(database)
    if len({source.resolve(), backup.resolve(), database.resolve()}) != 3:
        raise RuntimeError("Integrity verification requires distinct paths")
    if not all(path.is_file() for path in (source, backup, database)):
        raise RuntimeError("Integrity verification requires all three artifacts")
    try:
        original = source.read_bytes()
        backed_up = backup.read_bytes()
        if original != backed_up:
            raise RuntimeError("Source JSON differs from its original backup")
        state = parse_unique_json(backed_up)
        if not isinstance(state, dict):
            raise RuntimeError("Backup JSON state must be an object")
        normalized = dict(state)
        for section in SECTIONS:
            normalized.setdefault(section, {})
        validate_snapshot(normalized)
        snapshot = read_snapshot(database)
        if snapshot != normalized:
            raise RuntimeError("SQLite snapshot differs from JSON backup")
        # Detect source/backup replacement during the verification itself.
        if source.read_bytes() != original or backup.read_bytes() != backed_up:
            raise RuntimeError("JSON state changed during integrity verification")
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise RuntimeError("Migration integrity verification could not complete") from exc
