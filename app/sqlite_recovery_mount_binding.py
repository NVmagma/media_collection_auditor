"""Advisory cross-container mount-root mapping for SQLite move diagnostics.

Operator-supplied root strings are NOT evidence of actual Docker mounts.
No filesystem or network access. Never authorizes reconciliation.
"""

from __future__ import annotations

import os
from typing import Any


def _normal_absolute(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and os.path.isabs(value)
        and os.path.normpath(value) == value
        and not any(part in (".", "..") for part in value.split(os.sep))
    )


def _relative_child(path: str, root: str) -> str | None:
    if path == root:
        return ""
    prefix = root if root == os.sep else root + os.sep
    if not path.startswith(prefix):
        return None
    return path[len(prefix):]


def inspect_mount_namespace_binding(
    *,
    local_destination: Any,
    jellyfin_path: Any,
    arr_path: Any,
    media_type: Any,
    roots: Any,
) -> dict[str, str]:
    """Compare relative names under explicit, service-specific mount roots.

    The roots must be independently verified by an operator; their presence
    here cannot establish a mount mapping, object identity, or a completed move.
    """
    blocked = {
        "status": "blocked",
        "authorization": "not_authorized",
        "mount_binding": "unverified",
    }
    if media_type not in ("Movie", "Series"):
        return {**blocked, "reason": "invalid_media_type"}
    if not isinstance(roots, dict) or set(roots) != {"local", "jellyfin", "arr"}:
        return {**blocked, "reason": "mount_roots_unavailable"}
    if not all(_normal_absolute(roots[k]) for k in ("local", "jellyfin", "arr")):
        return {**blocked, "reason": "invalid_mount_roots"}
    if not all(_normal_absolute(p) for p in (local_destination, jellyfin_path, arr_path)):
        return {**blocked, "reason": "invalid_observed_paths"}
    # Jellyfin movies are files; the corresponding Arr record is a title directory.
    jf_directory = os.path.dirname(jellyfin_path) if media_type == "Movie" else jellyfin_path
    paths = (local_destination, jf_directory, arr_path)
    relative = tuple(_relative_child(p, roots[k]) for p, k in zip(paths, ("local", "jellyfin", "arr")))
    if any(p is None for p in relative):
        return {**blocked, "reason": "path_outside_declared_mount"}
    if not all(relative):
        return {**blocked, "reason": "mount_root_not_title"}
    if len(set(relative)) != 1:
        return {**blocked, "reason": "relative_paths_disagree"}
    return {
        **blocked,
        "mount_binding": "relative_paths_consistent_unverified",
        "reason": "declared_mount_mapping_not_proof",
    }
