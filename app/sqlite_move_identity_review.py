"""Read-only move identity assessment for isolated SQLite recovery.

A matching inode on one device supports a rename hypothesis, but is NOT
sufficient to clear a durable intent: inode reuse, mount changes and races
remain possible. Cross-filesystem copies cannot satisfy this contract.
"""

from __future__ import annotations

import os

from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_persisted_recovery_review import review_persisted_move
from app.sqlite_recovery_fingerprint import capture_directory_fingerprint

BLOCKED = {
    "status": "blocked", "authorization": "not_authorized",
    "checkpoint_allowed": False, "intent_clearance": "blocked",
    "replay_allowed": False, "production_activation": "disabled",
}


def review_rename_identity(session, *, operation_id, media_key,
                           stage_paths, source_stage, destination_stage):
    """Review a persisted intent and the rename identity without writing."""
    try:
        before, revision = session.read_verified_snapshot()
    except Exception:
        return {**BLOCKED, "reason": "sqlite_session_unverified"}
    pending = before.get(INTENTS_KEY)
    if not isinstance(pending, dict):
        return {**BLOCKED, "reason": "persisted_intent_missing"}

    # The existing binding and unique-location review must pass first.
    location = review_persisted_move(
        session, operation_id=operation_id, media_key=media_key,
        stage_paths=stage_paths, source_stage=source_stage,
        destination_stage=destination_stage,
    )
    if location["status"] != "advisory":
        return {**BLOCKED, "reason": location.get("reason", "location_unverified")}

    evidence = pending.get("details", {}).get("pre_move_evidence")
    recorded = evidence.get("fingerprint") if isinstance(evidence, dict) else None
    if not isinstance(recorded, dict):
        return {**BLOCKED, "reason": "fingerprint_unavailable"}
    source_path = stage_paths[source_stage]
    destination_path = stage_paths[destination_stage]
    source_now = capture_directory_fingerprint(source_path)
    destination_now = capture_directory_fingerprint(destination_path)
    if source_now["status"] != "missing" or destination_now["status"] != "captured":
        return {**BLOCKED, "reason": "source_or_destination_changed"}

    # Same-device identity is necessary for a rename; not proof that our
    # operation performed it. Never rely on ctime/mtime equality for rename.
    if (type(recorded.get("device")) is not int
            or type(recorded.get("inode")) is not int
            or recorded["device"] != destination_now["device"]
            or recorded["inode"] != destination_now["inode"]):
        return {**BLOCKED, "reason": "rename_identity_unverified"}

    # Recheck both location and durable state after the identity observation.
    again = review_persisted_move(
        session, operation_id=operation_id, media_key=media_key,
        stage_paths=stage_paths, source_stage=source_stage,
        destination_stage=destination_stage,
    )
    if again["status"] != "advisory":
        return {**BLOCKED, "reason": "location_changed_during_review"}
    try:
        after, after_revision = session.read_verified_snapshot()
    except Exception:
        return {**BLOCKED, "reason": "sqlite_session_changed_during_review"}
    if after_revision != revision or after != before:
        return {**BLOCKED, "reason": "sqlite_session_changed_during_review"}
    return {
        **BLOCKED, "status": "advisory",
        "reason": "same_device_inode_consistent_not_proof",
        "identity_assessment": "rename_consistent_unverified",
    }
