"""Read-only collection-wide SQLite decision preview.

No filesystem actions, Arr requests, Jellyfin calls, or intent clearance.
Callers must provide fresh Jellyfin signals; absent entries are unknown.
"""

from __future__ import annotations

from datetime import datetime

from app.sqlite_lifecycle_checkpoint_plan import CLOCKS
from app.sqlite_lifecycle_decision_bridge import review_decision
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_state import validate_snapshot
from app.state_store import GuardedSQLiteStateStore


def preview_collection(*, database, now, thresholds, signals_by_key,
                       favorites_trigger_keep=True):
    """Inspect an existing verified snapshot without changing it."""
    if not isinstance(now, datetime) or now.tzinfo is not None:
        raise ValueError("Naive local observation time required")
    if not isinstance(thresholds, dict) or set(thresholds) != {
            "Waiting", "Holding", "Removal", "Keep"}:
        raise ValueError("All lifecycle thresholds required")
    if any(type(value) is not int or value < 0 for value in thresholds.values()):
        raise ValueError("Invalid lifecycle threshold")
    if not isinstance(signals_by_key, dict):
        raise ValueError("Signals mapping required")
    snapshot, revision = GuardedSQLiteStateStore(database).load_with_revision()
    validate_snapshot(snapshot)
    locations = {}
    for stage, section in CLOCKS.items():
        for key in snapshot[section]:
            locations.setdefault(key, []).append(stage)
    results = []
    for key in sorted(locations):
        stages = locations[key]
        stage = stages[0]
        review = review_decision(
            snapshot, key, stage, now, thresholds[stage],
            signals_by_key.get(key), favorites_trigger_keep)
        results.append({"media_key": key, "tracked_stages": stages, **review})
    return {
        "status": "blocked" if snapshot.get(INTENTS_KEY) else "advisory",
        "authorization": "not_authorized",
        "production_activation": "disabled",
        "read_only": True,
        "revision": revision,
        "tracked_titles": len(results),
        "blocked_titles": sum(row["status"] == "blocked" for row in results),
        "decisions": results,
    }
