"""Advisory pre-move directory fingerprints for experimental SQLite recovery.

This module reads metadata only, does not traverse directory contents, and
never authorizes a move, replay, reconciliation, or deletion.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any


def capture_directory_fingerprint(path: Any) -> dict[str, Any]:
    """Capture metadata for a directory without following symbolic links.

    Fingerprints are process-local observations, not portable identity proofs:
    inode/device numbers can be reused or remapped across container mounts.
    """
    if (not isinstance(path, str) or not path or not os.path.isabs(path)
            or os.path.normpath(path) != path
            or any(part in (".", "..") for part in path.split(os.sep))):
        return {"status": "invalid_path"}
    current = Path("/")
    try:
        for component in Path(path).parts[1:]:
            current = current / component
            metadata = os.lstat(current)
            if stat.S_ISLNK(metadata.st_mode):
                return {"status": "symlink_unsafe"}
            if not stat.S_ISDIR(metadata.st_mode):
                return {"status": "not_directory"}
        first = os.lstat(path)
        second = os.lstat(path)
    except FileNotFoundError:
        return {"status": "missing"}
    except (OSError, ValueError):
        return {"status": "unavailable"}
    if not stat.S_ISDIR(first.st_mode) or not stat.S_ISDIR(second.st_mode):
        return {"status": "not_directory"}
    fields = ("st_dev", "st_ino", "st_mode", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(first, field) != getattr(second, field) for field in fields):
        return {"status": "changed_during_capture"}
    return {
        "status": "captured",
        "device": first.st_dev,
        "inode": first.st_ino,
        "mode": first.st_mode,
        "mtime_ns": first.st_mtime_ns,
        "ctime_ns": first.st_ctime_ns,
    }


def compare_directory_fingerprint(
    recorded: Any, observed: Any,
) -> dict[str, str]:
    """Compare captured metadata without exposing identifiers or granting trust."""
    blocked = {
        "status": "blocked",
        "authorization": "not_authorized",
        "fingerprint_binding": "unverified",
    }
    fields = ("device", "inode", "mode", "mtime_ns", "ctime_ns")
    if (not isinstance(recorded, dict) or not isinstance(observed, dict)
            or recorded.get("status") != "captured"
            or observed.get("status") != "captured"
            or any(type(item.get(field)) is not int for item in (recorded, observed)
                   for field in fields)):
        return {**blocked, "reason": "fingerprint_unavailable"}
    if any(recorded[field] != observed[field] for field in fields):
        return {**blocked, "reason": "fingerprint_mismatch"}
    return {
        **blocked,
        "fingerprint_binding": "metadata_consistent_unverified",
        "reason": "matching_metadata_not_proof",
    }
