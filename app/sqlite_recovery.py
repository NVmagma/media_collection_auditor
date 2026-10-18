"""Read-only diagnostics for interrupted offline SQLite conversions.

Never remove or overwrite artifacts automatically: a partial database or
backup may contain recoverable evidence. JSON remains authoritative.
"""

from __future__ import annotations

from pathlib import Path

from app.sqlite_json import parse_unique_json
from app.sqlite_state import SECTIONS, read_snapshot, validate_snapshot


def inspect_migration_artifacts(
    source: str | Path, backup: str | Path, database: str | Path
) -> dict[str, str]:
    """Classify artifacts without creating or modifying any files.

    Results are diagnostic only and must never authorize an audit or deletion.
    A valid snapshot is not proof the JSON source stayed unchanged.
    """
    source, backup, database = Path(source), Path(backup), Path(database)
    if len({source.resolve(), backup.resolve(), database.resolve()}) != 3:
        raise RuntimeError("Migration paths must be distinct")

    result: dict[str, str] = {}
    if not source.is_file():
        result["source"] = "missing"
    else:
        try:
            state = parse_unique_json(source.read_bytes())
            if not isinstance(state, dict):
                raise RuntimeError("Invalid JSON state")
            for section in SECTIONS:
                state.setdefault(section, {})
            validate_snapshot(state)
            result["source"] = "valid"
        except (OSError, UnicodeError, ValueError, TypeError, RuntimeError):
            result["source"] = "invalid"

    if not backup.exists():
        result["backup"] = "missing"
    elif not backup.is_file():
        result["backup"] = "invalid"
    else:
        try:
            state = parse_unique_json(backup.read_bytes())
            if not isinstance(state, dict):
                raise RuntimeError("Invalid backup")
            for section in SECTIONS:
                state.setdefault(section, {})
            validate_snapshot(state)
            result["backup"] = "valid"
        except (OSError, UnicodeError, ValueError, TypeError, RuntimeError):
            result["backup"] = "invalid"

    if not database.exists():
        result["database"] = "missing"
    elif not database.is_file():
        result["database"] = "invalid"
    else:
        try:
            read_snapshot(database)
            result["database"] = "complete"
        except RuntimeError:
            result["database"] = "incomplete_or_invalid"

    if result["source"] == "valid" and result["backup"] == "valid":
        try:
            result["source_backup"] = (
                "identical" if source.read_bytes() == backup.read_bytes()
                else "different"
            )
        except OSError:
            result["source_backup"] = "unreadable"
    else:
        result["source_backup"] = "unverified"
    return result


def inspect_migration_integrity_status(
    source: str | Path, backup: str | Path, database: str | Path
) -> dict[str, str]:
    """Add a fail-closed cross-artifact integrity status to recovery diagnostics.

    A structurally complete database is not necessarily identical to the
    backup. This is read-only and never authorizes activation or deletion.
    """
    from app.sqlite_integrity import verify_migration_integrity

    result = inspect_migration_artifacts(source, backup, database)
    if (result["source"] != "valid" or result["backup"] != "valid"
            or result["database"] != "complete"
            or result["source_backup"] != "identical"):
        result["integrity"] = "unverified"
        return result
    try:
        verify_migration_integrity(source, backup, database)
    except RuntimeError:
        result["integrity"] = "mismatch_or_unreadable"
    else:
        result["integrity"] = "verified"
    return result
