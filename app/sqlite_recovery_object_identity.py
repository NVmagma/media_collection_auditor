"""Advisory filesystem object observations for an interrupted media move.

Never use inode numbers as proof across mounts or authorize reconciliation.
No media contents are opened, hashed, moved, or modified.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any


def _observe_directory(path: Any) -> dict[str, Any]:
    if not isinstance(path, str) or not path or not os.path.isabs(path):
        return {"status": "invalid_path"}
    if os.path.normpath(path) != path or any(
        component in (".", "..") for component in path.split(os.sep)
    ):
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
        metadata = os.lstat(path)
    except FileNotFoundError:
        return {"status": "missing"}
    except (OSError, ValueError):
        return {"status": "unavailable"}
    return {"status": "present", "device": metadata.st_dev,
            "inode": metadata.st_ino}


def inspect_move_object_observation(source: Any, destination: Any) -> dict[str, str]:
    """Classify path objects without exposing filesystem identifiers."""
    base = {"status": "blocked", "authorization": "not_authorized",
            "object_identity": "unverified"}
    if source == destination:
        return {**base, "reason": "identical_paths"}
    before_source = _observe_directory(source)
    before_destination = _observe_directory(destination)
    after_source = _observe_directory(source)
    after_destination = _observe_directory(destination)
    if before_source != after_source or before_destination != after_destination:
        return {**base, "reason": "filesystem_changed_during_inspection"}
    if before_source["status"] != "missing" or before_destination["status"] != "present":
        return {**base, "reason": "not_destination_only"}
    # Even a stable inode is not tied to the original source object. Mount
    # remapping and races remain possible, so identity stays unverified.
    return {**base, "reason": "destination_object_observed_not_proven"}
