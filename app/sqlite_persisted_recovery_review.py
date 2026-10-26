"""Read-only recovery review from a revision-verified SQLite session.

Never trusts a caller-supplied intent and never clears, replays, or checkpoints.
"""

from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_recovery_intent_binding import review_bound_move


def review_persisted_move(session, *, operation_id, media_key,
                          stage_paths, source_stage, destination_stage):
    blocked = {
        "status": "blocked", "authorization": "not_authorized",
        "checkpoint_allowed": False, "intent_clearance": "blocked",
        "replay_allowed": False, "production_activation": "disabled",
    }
    try:
        snapshot, revision = session.read_verified_snapshot()
    except Exception:
        return {**blocked, "reason": "sqlite_session_unverified"}
    pending = snapshot.get(INTENTS_KEY)
    if not isinstance(pending, dict):
        return {**blocked, "reason": "persisted_intent_missing"}
    result = review_bound_move(
        pending_intent=pending, operation_id=operation_id,
        media_key=media_key, stage_paths=stage_paths,
        source_stage=source_stage, destination_stage=destination_stage,
    )
    # Reject observations if a concurrent writer changed the snapshot.
    try:
        confirmed, confirmed_revision = session.read_verified_snapshot()
    except Exception:
        return {**blocked, "reason": "sqlite_session_changed_during_review"}
    if confirmed_revision != revision or confirmed != snapshot:
        return {**blocked, "reason": "sqlite_session_changed_during_review"}
    return result
