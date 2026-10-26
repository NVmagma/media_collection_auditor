"""Fail-closed binding review for experimental SQLite move recovery.

Validation is advisory: even an exact match cannot clear an intent or authorize
filesystem operations. This does not change the production JSON backend.
"""

from __future__ import annotations

from app.sqlite_recovery_location_review import review_interrupted_move

STAGES = ("transient", "holding", "removal", "keep")


def review_bound_move(*, pending_intent, operation_id, media_key,
                      stage_paths, source_stage, destination_stage):
    """Check caller context against persisted intent before observing locations."""
    blocked = {
        "status": "blocked", "authorization": "not_authorized",
        "checkpoint_allowed": False, "intent_clearance": "blocked",
        "replay_allowed": False, "production_activation": "disabled",
    }
    if (not isinstance(pending_intent, dict)
            or not isinstance(operation_id, str) or not operation_id
            or pending_intent.get("id") != operation_id):
        return {**blocked, "reason": "operation_identity_mismatch"}
    if not isinstance(media_key, str) or not media_key:
        return {**blocked, "reason": "invalid_media_identity"}
    if (source_stage not in STAGES or destination_stage not in STAGES
            or source_stage == destination_stage
            or not isinstance(stage_paths, dict)
            or set(stage_paths) != set(STAGES)):
        return {**blocked, "reason": "invalid_stage_binding"}
    details = pending_intent.get("details")
    if not isinstance(details, dict):
        return {**blocked, "reason": "missing_intent_details"}
    if (details.get("media_key") != media_key
            or details.get("source") != stage_paths[source_stage]
            or details.get("destination") != stage_paths[destination_stage]):
        return {**blocked, "reason": "persisted_move_binding_mismatch"}
    if any(not isinstance(path, str) or not path for path in stage_paths.values()):
        return {**blocked, "reason": "invalid_stage_binding"}
    return review_interrupted_move(
        pending_intent=pending_intent, stage_paths=stage_paths,
        expected_destination=destination_stage,
    )
