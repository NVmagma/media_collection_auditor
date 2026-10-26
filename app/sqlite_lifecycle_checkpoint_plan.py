"""Pure advisory plans for lifecycle tracking; no media operations or writes."""

from copy import deepcopy
from datetime import datetime

from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_state import validate_snapshot

CLOCKS = {"Waiting": "first_seen", "Holding": "queued", "Removal": "in_removal", "Keep": "keep_seen"}
TRANSITIONS = {
    ("Waiting", "Holding"), ("Waiting", "Keep"),
    ("Holding", "Removal"), ("Holding", "Keep"), ("Removal", "Keep"),
}


def plan_lifecycle_checkpoint(state, *, media_key, source_stage, destination_stage,
                              observed_at, destination_observation):
    """Return a detached hypothetical snapshot; never authorize checkpointing."""
    if not isinstance(media_key, str) or not media_key:
        raise ValueError("A media key is required")
    if (source_stage, destination_stage) not in TRANSITIONS:
        raise ValueError("Unsupported lifecycle transition")
    if not isinstance(observed_at, datetime) or observed_at.tzinfo is not None:
        raise ValueError("Observation must be a naive datetime")
    if observed_at > datetime.now():
        raise ValueError("Future observation")
    if destination_observation not in ("unique", "missing", "ambiguous"):
        raise ValueError("Invalid destination observation")
    validate_snapshot(state)
    if INTENTS_KEY in state:
        raise RuntimeError("Unresolved operation intent")
    source = CLOCKS[source_stage]
    destination = CLOCKS[destination_stage]
    if media_key not in state[source]:
        raise RuntimeError("Source clock unavailable")
    if any(media_key in state[section] for section in CLOCKS.values()
           if section != source):
        raise RuntimeError("Conflicting lifecycle clocks")
    result = {"authorization": "not_authorized", "checkpoint_allowed": False,
              "production_activation": "disabled"}
    if destination_observation != "unique":
        return {**result, "status": "blocked", "planned_state": None}
    planned = deepcopy(state)
    planned[source].pop(media_key)
    planned[destination][media_key] = observed_at.isoformat()
    validate_snapshot(planned)
    return {**result, "status": "advisory", "planned_state": planned}
