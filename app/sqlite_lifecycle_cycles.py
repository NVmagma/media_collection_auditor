"""Pure multi-cycle lifecycle simulation; never applies filesystem or DB changes.

A transition here is a hypothetical model, not an operation authorization.
Only explicit, supplied Jellyfin signals may support a simulated transition.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from app.lifecycle_decisions import decide

_CLOCKS = {"Waiting": "first_seen", "Holding": "queued", "Removal": "in_removal"}
_TRANSITIONS = {
    ("Waiting", "keep"): "Keep",
    ("Waiting", "hold"): "Holding",
    ("Holding", "rescue"): "Keep",
    ("Holding", "to_removal"): "Removal",
}


def simulate_lifecycle_cycles(
    state: dict[str, Any],
    *,
    media_key: str,
    initial_stage: str,
    cycles: list[dict[str, Any]],
    favorites_trigger_keep: bool = True,
) -> dict[str, Any]:
    """Model decisions across ordered audit times using a detached state copy.

    Does not write SQLite, JSON or media. Removal candidates are never applied.
    """
    if not isinstance(media_key, str) or not media_key:
        raise ValueError("media_key must be nonempty")
    if initial_stage not in _CLOCKS:
        raise ValueError("initial_stage must be Waiting, Holding or Removal")
    if not isinstance(cycles, list):
        raise ValueError("cycles must be a list")
    simulated = deepcopy(state)
    stage = initial_stage
    history = []
    previous = None
    for cycle in cycles:
        if not isinstance(cycle, dict):
            raise ValueError("Invalid cycle")
        now, days, signals = (
            cycle.get("now"), cycle.get("wait_days"), cycle.get("signals")
        )
        if not isinstance(now, datetime) or now.tzinfo is not None:
            raise ValueError("Cycle time must be a naive datetime")
        if previous is not None and now <= previous:
            raise ValueError("Cycle times must increase")
        if type(days) is not int or days < 0:
            raise ValueError("wait_days must be a nonnegative integer")
        if signals is not None and not isinstance(signals, dict):
            raise ValueError("signals must be a dictionary or None")
        previous = now
        if stage == "Keep":
            action, reason = "none", "Simulated Keep stage; no further transition."
        else:
            stamp = simulated[_CLOCKS[stage]].get(media_key)
            if stamp is None:
                action, reason = "unknown", "Tracking clock unavailable."
            else:
                started = datetime.fromisoformat(stamp)
                if started > now:
                    action, reason = "unknown", "Tracking clock is in the future."
                elif signals is None:
                    action, reason = "unknown", "Jellyfin protection data unavailable."
                else:
                    action, reason = decide(
                        stage, (now - started).days, days, signals,
                        favorites_trigger_keep,
                    )
        destination = _TRANSITIONS.get((stage, action))
        prior_stage = stage
        if destination is not None:
            simulated[_CLOCKS[stage]].pop(media_key)
            if destination in _CLOCKS:
                simulated[_CLOCKS[destination]][media_key] = now.isoformat()
            elif destination == "Keep":
                simulated["keep_seen"][media_key] = now.isoformat()
            stage = destination
        history.append({
            "at": now.isoformat(),
            "stage_before": prior_stage,
            "decision": action,
            "stage_after": stage,
            "explanation": reason,
            "authorization": "not_authorized",
        })
    return {
        "history": history,
        "simulated_state": simulated,
        "final_stage": stage,
        "authorization": "not_authorized",
        "persistence": "none",
        "production_activation": "disabled",
    }
