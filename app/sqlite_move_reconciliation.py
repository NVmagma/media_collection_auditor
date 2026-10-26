"""Read-only filesystem reconciliation for interrupted SQLite move intents.

No files are moved, deleted, or renamed. Ambiguous paths and symlinks fail
closed. A verified destination does not by itself authorize clearing intent:
the caller must also reconcile tracking and any external Arr side effects.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def inspect_move_intent(details: dict[str, Any]) -> str:
    """Return 'not_started' or 'destination_present'; refuse ambiguous moves.

    Paths must be absolute, distinct, non-symlink directories with existing
    non-symlink parents. A missing source and destination is never success.
    """
    if not isinstance(details, dict):
        raise RuntimeError("Move intent details are invalid")
    source_raw, target_raw = details.get("source"), details.get("destination")
    if not all(isinstance(value, str) and value for value in (source_raw, target_raw)):
        raise RuntimeError("Move intent requires source and destination paths")
    source, target = Path(source_raw), Path(target_raw)
    if not source.is_absolute() or not target.is_absolute() or source == target:
        raise RuntimeError("Move intent paths must be absolute and distinct")
    for path in (source, target):
        if ".." in path.parts:
            raise RuntimeError("Move intent path traversal is not allowed")
        # Reject symlinks anywhere in the existing path chain, not only leaf.
        for part in (path, *path.parents):
            if part.is_symlink():
                raise RuntimeError("Move intent path contains a symlink")
        if not path.parent.is_dir():
            raise RuntimeError("Move intent parent is unavailable")
    source_exists = source.exists()
    target_exists = target.exists()
    if source_exists and target_exists:
        raise RuntimeError("Ambiguous move: both source and destination exist")
    if not source_exists and not target_exists:
        raise RuntimeError("Unresolved move: both source and destination missing")
    existing = source if source_exists else target
    if not existing.is_dir():
        raise RuntimeError("Move intent location is not a directory")
    return "not_started" if source_exists else "destination_present"
