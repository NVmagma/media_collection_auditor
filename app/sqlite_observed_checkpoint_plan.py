"""Combine independent read-only location observation with advisory planning.

This never authorizes a checkpoint, reconciles an intent or moves media.
"""

from __future__ import annotations

from app.sqlite_lifecycle_checkpoint_plan import plan_lifecycle_checkpoint
from app.sqlite_lifecycle_observation import observe_lifecycle_location
from app.sqlite_operation_coordinator import INTENTS_KEY

DESTINATIONS = {
    "Waiting": "transient",
    "Holding": "holding",
    "Removal": "removal",
    "Keep": "keep",
}


def plan_from_observed_location(
    state, *, media_key, source_stage, destination_stage, observed_at,
    stage_paths,
):
    """Return an advisory plan only when the title is uniquely at destination.

    Filesystem observation is evidence of location, not proof of a completed
    move or of Jellyfin protection. Never grant checkpoint permission.
    """
    if not isinstance(state, dict) or INTENTS_KEY in state:
        raise RuntimeError("Unresolved operation intent or invalid state")
    if destination_stage not in DESTINATIONS:
        raise ValueError("Unsupported destination stage")
    observed = observe_lifecycle_location(stage_paths)
    if observed["status"] != "observed":
        return {
            "status": "blocked", "reason": observed["reason"],
            "planned_state": None, "authorization": "not_authorized",
            "checkpoint_allowed": False, "production_activation": "disabled",
        }
    if observed["stage"] != DESTINATIONS[destination_stage]:
        return {
            "status": "blocked", "reason": "observed_stage_mismatch",
            "planned_state": None, "authorization": "not_authorized",
            "checkpoint_allowed": False, "production_activation": "disabled",
        }
    return plan_lifecycle_checkpoint(
        state, media_key=media_key, source_stage=source_stage,
        destination_stage=destination_stage, observed_at=observed_at,
        destination_observation="unique",
    )
