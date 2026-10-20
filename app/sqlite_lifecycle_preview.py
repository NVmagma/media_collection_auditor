"""Read-only lifecycle previews against isolated SQLite tracking snapshots.

Never fetches Jellyfin signals, dispatches media actions, or authorizes deletion.
"""

from __future__ import annotations

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
