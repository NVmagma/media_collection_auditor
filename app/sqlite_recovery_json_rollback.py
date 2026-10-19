"""Read-only JSON rollback readiness for an experimental SQLite migration.

Rollback means continuing to use the original JSON; this module never copies
backup bytes over production state or modifies any media.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from app.sqlite_json import parse_unique_json
from app.sqlite_state import SECTIONS, validate_snapshot


def inspect_json_rollback_readiness(source: str | Path, backup: str | Path) -> dict[str, Any]:
    """Compare exact JSON bytes without exposing state contents or paths."""
    blocked = {"status": "blocked", "authorization": "not_authorized",
               "storage_authority": "json", "production_activation": "disabled",
               "restore_performed": False, "media_actions_performed": False}
    source, backup = Path(source), Path(backup)
    if source.is_symlink() or backup.is_symlink():
        return {**blocked, "reason": "symlink_unsafe"}
    if source == backup or source.resolve() == backup.resolve():
        return {**blocked, "reason": "paths_not_distinct"}
    try:
        original = source.read_bytes()
        archived = backup.read_bytes()
    except (OSError, ValueError):
        return {**blocked, "reason": "state_unavailable"}
    try:
        parsed = parse_unique_json(original)
        saved = parse_unique_json(archived)
        if not isinstance(parsed, dict) or not isinstance(saved, dict):
            return {**blocked, "reason": "state_invalid"}
        for state in (parsed, saved):
            normalized = dict(state)
            for section in SECTIONS:
                normalized.setdefault(section, {})
            validate_snapshot(normalized)
    except (RuntimeError, ValueError, TypeError, UnicodeError):
        return {**blocked, "reason": "state_invalid"}
    if hashlib.sha256(original).digest() != hashlib.sha256(archived).digest():
        return {**blocked, "reason": "json_backup_diverged"}
    return {**blocked, "reason": "matching_json_backup_advisory_only",
            "backup_integrity": "matching_bytes_untrusted"}
