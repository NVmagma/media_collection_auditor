"""Advisory recovery review of an interrupted move; never clear intent."""

from __future__ import annotations

from app.sqlite_lifecycle_observation import observe_lifecycle_location
from app.sqlite_recovery_fingerprint import (
    capture_directory_fingerprint, compare_directory_fingerprint,
)
from app.sqlite_recovery_pre_move_evidence import validate_pre_move_evidence


def review_interrupted_move(*, pending_intent, stage_paths, expected_destination):
    """Read fresh location metadata without treating it as proof of a move."""
    blocked = {"status": "blocked", "authorization": "not_authorized",
               "checkpoint_allowed": False, "intent_clearance": "blocked",
               "replay_allowed": False, "production_activation": "disabled"}
    if (not isinstance(pending_intent, dict)
            or pending_intent.get("kind") != "move"
            or pending_intent.get("phase") not in
            ("intent_recorded", "applied_pending_reconciliation")):
        return {**blocked, "reason": "invalid_pending_move"}
    details = pending_intent.get("details")
    if not isinstance(details, dict):
        return {**blocked, "reason": "missing_intent_details"}
    evidence = details.get("pre_move_evidence")
    if validate_pre_move_evidence(evidence)["evidence_verification"] != "schema_valid_untrusted":
        return {**blocked, "reason": "invalid_pre_move_evidence"}
    if expected_destination not in ("transient", "holding", "removal", "keep"):
        return {**blocked, "reason": "invalid_destination"}
    observed = observe_lifecycle_location(stage_paths)
    if observed["status"] != "observed":
        return {**blocked, "reason": observed["reason"]}
    if observed["stage"] != expected_destination:
        return {**blocked, "reason": "destination_mismatch"}
    fresh = capture_directory_fingerprint(stage_paths[expected_destination])
    comparison = compare_directory_fingerprint(evidence["fingerprint"], fresh)
    return {**blocked, "status": "advisory",
            "reason": comparison["reason"],
            "fingerprint_binding": comparison["fingerprint_binding"]}
