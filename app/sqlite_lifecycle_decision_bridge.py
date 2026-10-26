"""Read-only parity bridge using the production lifecycle decision function."""

from datetime import datetime

from app.lifecycle_decisions import decide
from app.sqlite_lifecycle_checkpoint_plan import CLOCKS
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_state import validate_snapshot


def review_decision(snapshot, media_key, stage, now, threshold_days,
                    signals=None, favorites_trigger_keep=True):
    """Return an advisory decision; never authorize media side effects."""
    validate_snapshot(snapshot)
    if stage not in CLOCKS or not isinstance(media_key, str) or not media_key:
        raise ValueError("Invalid lifecycle identity")
    if not isinstance(now, datetime) or now.tzinfo is not None:
        raise ValueError("Invalid observation time")
    if type(threshold_days) is not int or threshold_days < 0:
        raise ValueError("Invalid threshold")
    if signals is not None and not isinstance(signals, dict):
        raise ValueError("Invalid Jellyfin signals")

    blockers = []
    if snapshot.get(INTENTS_KEY):
        blockers.append("unresolved_sqlite_operation")
    clock = CLOCKS[stage]
    matches = [name for name in CLOCKS.values() if media_key in snapshot[name]]
    age = None
    if matches != [clock]:
        blockers.append("missing_or_conflicting_clock")
    else:
        observed = datetime.fromisoformat(snapshot[clock][media_key])
        if observed > now:
            blockers.append("future_observation")
        else:
            age = (now - observed).days
    if signals is None:
        blockers.append("jellyfin_unavailable")
    if stage == "Removal":
        blockers.append("deletion_not_authorized")
    candidate, reason = decide(stage, age, threshold_days, signals,
                               favorites_trigger_keep)
    return {
        "status": "blocked" if blockers else "advisory",
        "action": "none" if blockers else candidate,
        "candidate_action": candidate,
        "explanation": reason,
        "blockers": blockers,
        "authorization": "not_authorized",
        "read_only": True,
    }
