"""Read-only multi-title lifecycle rehearsal against one verified SQLite snapshot.

Inputs describe disposable titles and supplied Jellyfin signals. Never probes
services, mutates tracking, or dispatches media operations.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from app.lifecycle_decisions import decide
from app.sqlite_isolated_adapter import inspect_isolated_audit_state

_STAGE_CLOCKS = {
    "Waiting": "first_seen",
    "Holding": "queued",
    "Removal": "in_removal",
}


def rehearse_isolated_lifecycle(
    source_json: str | Path,
    backup_json: str | Path,
    database: str | Path,
    *,
    titles: list[dict[str, Any]],
    now: datetime,
    favorites_trigger_keep: bool = True,
) -> dict[str, Any]:
    """Preview titles from a single snapshot, with no action authorization.

    Each title supplies media_key, stage, wait_days and optional signals.
    Unknown Jellyfin protection always yields unknown, even in Removal.
    """
    if not isinstance(now, datetime) or now.tzinfo is not None:
        raise ValueError("now must be a naive local datetime")
    if not isinstance(titles, list):
        raise ValueError("titles must be a list")
    seen = set()
    for item in titles:
        if not isinstance(item, dict):
            raise ValueError("Invalid title specification")
        key, stage, days = (
            item.get("media_key"), item.get("stage"), item.get("wait_days")
        )
        if not isinstance(key, str) or not key or key in seen:
            raise ValueError("Missing or duplicate media key")
        if stage not in _STAGE_CLOCKS:
            raise ValueError("Unsupported lifecycle stage")
        if type(days) is not int or days < 0:
            raise ValueError("wait_days must be a nonnegative integer")
        signals = item.get("signals")
        if signals is not None and not isinstance(signals, dict):
            raise ValueError("signals must be a dictionary or None")
        seen.add(key)

    snapshot = inspect_isolated_audit_state(source_json, backup_json, database)
    results = []
    for item in titles:
        key, stage = item["media_key"], item["stage"]
        stamp = snapshot["state"][_STAGE_CLOCKS[stage]].get(key)
        if stamp is None:
            action, reason = "unknown", "Tracking clock unavailable."
        else:
            started = datetime.fromisoformat(stamp)
            if started > now:
                action, reason = "unknown", "Tracking clock is in the future."
            elif item.get("signals") is None:
                action, reason = "unknown", "Jellyfin protection data unavailable."
            else:
                action, reason = decide(
                    stage, (now - started).days, item["wait_days"],
                    item["signals"], favorites_trigger_keep,
                )
        results.append({
            "media_key": key,
            "stage": stage,
            "decision": action,
            "explanation": reason,
            "authorization": "not_authorized",
        })
    return {
        "revision": snapshot["revision"],
        "titles": results,
        "authorization": "not_authorized",
        "production_activation": "disabled",
        "storage_authority": "json",
    }
