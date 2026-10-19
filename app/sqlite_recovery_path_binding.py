"""Read-only comparison of recorded move paths and remote media paths.

String agreement is only advisory: container mount namespaces may differ and
neither service paths nor directory existence establish filesystem identity.
"""

from __future__ import annotations

import os
from typing import Any


def _absolute_normal_path(value: Any) -> bool:
    return (isinstance(value, str) and bool(value) and
            os.path.isabs(value) and os.path.normpath(value) == value and
            not any(part in (".", "..") for part in value.split(os.sep)))


def inspect_move_path_binding(
    intent: dict[str, Any], *,
    jellyfin_record: dict[str, Any] | None,
    arr_record: dict[str, Any] | None,
    filesystem_interpretation: str,
) -> dict[str, str]:
    """Compare paths without normalizing away traversal or authorizing a move."""
    base = {"status": "blocked", "authorization": "not_authorized",
            "path_binding": "unverified"}
    if not isinstance(intent, dict) or not isinstance(jellyfin_record, dict) or not isinstance(arr_record, dict):
        return {**base, "reason": "missing_path_evidence"}
    source, destination = intent.get("source"), intent.get("destination")
    if (not _absolute_normal_path(source) or not _absolute_normal_path(destination)
            or source == destination):
        return {**base, "reason": "invalid_intent_paths"}
    media_type = intent.get("jellyfin_type")
    if media_type not in ("Movie", "Series"):
        return {**base, "reason": "invalid_media_type"}
    jf_path = jellyfin_record.get("Path")
    arr_path = arr_record.get("path")
    if not _absolute_normal_path(jf_path) or not _absolute_normal_path(arr_path):
        return {**base, "reason": "remote_path_unavailable"}
    # Jellyfin movie Path normally points to the media file, whereas series
    # and Arr title paths commonly point to a directory. Do not guess the
    # directory for movies from a filename; treat it as ambiguous.
    if media_type == "Movie":
        return {**base, "reason": "movie_file_path_requires_binding"}
    if jf_path not in (source, destination) or arr_path not in (source, destination):
        return {**base, "reason": "remote_path_mismatch"}
    if jf_path != arr_path:
        return {**base, "reason": "service_paths_disagree"}
    if filesystem_interpretation != "destination_only_unverified":
        return {**base, "reason": "filesystem_not_destination_only"}
    if jf_path != destination:
        return {**base, "reason": "destination_path_not_observed"}
    return {**base, "path_binding": "path_strings_consistent_unverified",
            "reason": "path_strings_match_not_proof"}
