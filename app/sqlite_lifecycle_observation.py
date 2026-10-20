"""Read-only lifecycle location observations for disposable SQLite rehearsals.

Observations never prove a move, authorize checkpointing or clear pending intents.
"""

from __future__ import annotations

from app.sqlite_recovery_fingerprint import capture_directory_fingerprint

STAGES = ("transient", "holding", "removal", "keep")


def observe_lifecycle_location(stage_paths: dict[str, str]) -> dict[str, object]:
    """Inspect all four explicit absolute paths without following symlinks.

    Fail closed on any invalid, inaccessible, or unstable directory; a missing
    directory is permitted because a title should occupy only one stage.
    """
    blocked = {"status": "blocked", "authorization": "not_authorized",
               "checkpoint_allowed": False}
    if not isinstance(stage_paths, dict) or set(stage_paths) != set(STAGES):
        return {**blocked, "reason": "invalid_stage_paths"}
    if any(not isinstance(path, str) for path in stage_paths.values()):
        return {**blocked, "reason": "invalid_stage_paths"}
    if len(set(stage_paths.values())) != len(STAGES):
        return {**blocked, "reason": "duplicate_stage_paths"}
    observations = {stage: capture_directory_fingerprint(stage_paths[stage])
                    for stage in STAGES}
    if any(value["status"] not in ("captured", "missing")
           for value in observations.values()):
        return {**blocked, "reason": "unsafe_or_unavailable_path"}
    present = [stage for stage in STAGES
               if observations[stage]["status"] == "captured"]
    if len(present) == 0:
        return {**blocked, "reason": "media_missing"}
    if len(present) != 1:
        return {**blocked, "reason": "media_ambiguous"}
    return {**blocked, "status": "observed", "reason": "unique_location_unverified",
            "stage": present[0], "observation": "unique"}
