"""Experimental read-only lifecycle reconciliation candidate.

A candidate is NOT a trusted move proof. It is never committed or returned as
authorization. Production JSON state and filesystem operations are untouched.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime

from app.sqlite_lifecycle_checkpoint_plan import CLOCKS, TRANSITIONS
from app.sqlite_move_identity_review import review_rename_identity
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_state import validate_snapshot

BLOCKED = {
    "status": "blocked", "authorization": "not_authorized",
    "checkpoint_allowed": False, "intent_clearance": "blocked",
    "replay_allowed": False, "production_activation": "disabled",
}


def plan_atomic_move_reconciliation(session, *, operation_id, media_key,
                                    stage_paths, source_stage, destination_stage,
                                    observed_at):
    """Model one future atomic state transition without writing or clearance."""
    if (not isinstance(observed_at, datetime) or observed_at.tzinfo is not None
            or observed_at > datetime.now()):
        return {**BLOCKED, "reason": "invalid_observation_time"}
    if (source_stage, destination_stage) not in TRANSITIONS:
        return {**BLOCKED, "reason": "unsupported_lifecycle_transition"}
    try:
        original, revision = session.read_verified_snapshot()
        validate_snapshot(original)
    except Exception:
        return {**BLOCKED, "reason": "sqlite_session_unverified"}
    pending = original.get(INTENTS_KEY)
    if not isinstance(pending, dict):
        return {**BLOCKED, "reason": "persisted_intent_missing"}
    if pending.get("phase") not in ("intent_recorded", "applied_pending_reconciliation"):
        return {**BLOCKED, "reason": "invalid_intent_phase"}
    source_clock = CLOCKS[source_stage]
    destination_clock = CLOCKS[destination_stage]
    if media_key not in original[source_clock]:
        return {**BLOCKED, "reason": "source_clock_missing"}
    if any(media_key in original[section] for section in CLOCKS.values()
           if section != source_clock):
        return {**BLOCKED, "reason": "conflicting_lifecycle_clocks"}

    identity = review_rename_identity(
        session, operation_id=operation_id, media_key=media_key,
        stage_paths=stage_paths, source_stage=source_stage,
        destination_stage=destination_stage,
    )
    if identity.get("identity_assessment") != "rename_consistent_unverified":
        return {**BLOCKED, "reason": identity.get("reason", "identity_unverified")}

    # One detached snapshot contains BOTH proposed changes. The guarded store
    # can eventually commit it with one revision CAS, after trusted verification
    # exists. Never pass this candidate to an automatic checkpoint today.
    candidate = deepcopy(original)
    del candidate[source_clock][media_key]
    candidate[destination_clock][media_key] = observed_at.isoformat()
    del candidate[INTENTS_KEY]
    try:
        validate_snapshot(candidate)
        confirmed, confirmed_revision = session.read_verified_snapshot()
    except Exception:
        return {**BLOCKED, "reason": "sqlite_session_changed_during_review"}
    if confirmed_revision != revision or confirmed != original:
        return {**BLOCKED, "reason": "sqlite_session_changed_during_review"}
    return {
        **BLOCKED, "status": "advisory",
        "reason": "trusted_move_proof_required",
        "expected_revision": revision,
        "candidate_state": candidate,
    }
