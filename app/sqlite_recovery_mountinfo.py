"""Conservative read-only Linux mountinfo diagnostics for SQLite recovery.

A mountinfo record is local to one process namespace; it cannot establish
cross-container identity, media safety, or reconciliation authorization.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def inspect_mountinfo(path: Any, mountinfo: str) -> dict[str, str]:
    blocked = {"status": "blocked", "authorization": "not_authorized",
               "mount_identity": "unverified"}
    if (not isinstance(path, str) or not os.path.isabs(path)
            or os.path.normpath(path) != path
            or any(part in (".", "..") for part in path.split("/"))):
        return {**blocked, "reason": "invalid_path"}
    if not isinstance(mountinfo, str) or not mountinfo:
        return {**blocked, "reason": "mountinfo_unavailable"}
    # Linux mountinfo: optional fields precede ' - '; field 5 is mount point.
    # Refuse ambiguous escaped paths, duplicate matches, and malformed lines.
    candidates = []
    for line in mountinfo.splitlines():
        halves = line.split(" - ")
        if len(halves) != 2:
            return {**blocked, "reason": "mountinfo_malformed"}
        fields = halves[0].split()
        if len(fields) < 6 or len(halves[1].split()) < 3:
            return {**blocked, "reason": "mountinfo_malformed"}
        mount = fields[4]
        if "\\" in mount:
            return {**blocked, "reason": "mountinfo_escaped_path_unverified"}
        if not os.path.isabs(mount) or os.path.normpath(mount) != mount:
            return {**blocked, "reason": "mountinfo_malformed"}
        if path == mount or path.startswith(mount.rstrip("/") + "/"):
            candidates.append(mount)
    if not candidates:
        return {**blocked, "reason": "no_matching_mount"}
    longest = max(len(m) for m in candidates)
    if sum(len(m) == longest for m in candidates) != 1:
        return {**blocked, "reason": "ambiguous_mount"}
    return {**blocked, "mount_identity": "local_namespace_observed_unverified",
            "reason": "cross_container_identity_not_established"}


def inspect_current_namespace(path: str, mountinfo_path: Path = Path("/proc/self/mountinfo")) -> dict[str, str]:
    try:
        contents = mountinfo_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        contents = ""
    return inspect_mountinfo(path, contents)
