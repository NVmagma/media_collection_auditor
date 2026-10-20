"""Read-only lifecycle previews against isolated SQLite tracking snapshots.

Never fetches Jellyfin signals, dispatches media actions, or authorizes deletion.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from app.sqlite_isolated_adapter import inspect_isolated_audit_state
from app.lifecycle_decisions import decide


def preview_isolated_lifecycle(
    source_json: str | Path,
    backup_json: str | Path,
    database: str | Path,
    *,
    stage: str,
    age_days: int | None,
    wait_days: int,
    signals: dict[str, Any] | None = None,
    favorites_trigger_keep: bool = True,
) -> dict[str, Any]:
    """Compute an advisory decision without acting on any media or state."""
    report = inspect_isolated_audit_state(source_json, backup_json, database)
    action, explanation = decide(
        stage, age_days, wait_days, signals, favorites_trigger_keep
    )
    return {
        "revision": report["revision"],
        "decision": action,
        "explanation": explanation,
        "authorization": "not_authorized",
        "production_activation": "disabled",
        "storage_authority": "json",
    }


def preview_tracked_lifecycle(
    source_json: str | Path,
    backup_json: str | Path,
    database: str | Path,
    *,
    media_key: str,
    stage: str,
    wait_days: int,
    signals: dict[str, Any] | None = None,
    favorites_trigger_keep: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Preview a tracked title using its persisted stage clock.

    Missing clocks or unavailable Jellyfin data produce 'unknown', including
    for Removal. This preview cannot authorize a move or deletion.
    """
    if not isinstance(media_key, str) or not media_key:
        raise ValueError("A nonempty media key is required")
    if type(wait_days) is not int or wait_days < 0:
        raise ValueError("wait_days must be a nonnegative integer")
    if stage not in ("Waiting", "Holding", "Removal"):
        raise ValueError("Unsupported lifecycle stage")
    clock_section = {
        "Waiting": "first_seen",
        "Holding": "queued",
        "Removal": "in_removal",
    }[stage]
    report = inspect_isolated_audit_state(source_json, backup_json, database)
    stamp = report["state"][clock_section].get(media_key)
    action, explanation = "unknown", "Tracking clock unavailable; no action proposed."
    if stamp is not None:
        instant = now if now is not None else datetime.now()
        if not isinstance(instant, datetime) or instant.tzinfo is not None:
            raise ValueError("now must be a naive local datetime")
        started = datetime.fromisoformat(stamp)
        if started > instant:
            action, explanation = "unknown", "Tracking clock is in the future."
        elif signals is None:
            action, explanation = "unknown", "Jellyfin protection data unavailable."
        else:
            age_days = (instant - started).days
            action, explanation = decide(
                stage, age_days, wait_days, signals, favorites_trigger_keep
            )
    return {
        "media_key": media_key,
        "stage": stage,
        "revision": report["revision"],
        "decision": action,
        "explanation": explanation,
        "authorization": "not_authorized",
        "production_activation": "disabled",
        "storage_authority": "json",
    }
