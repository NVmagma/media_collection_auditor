"""Read-only restart rehearsal from verified disposable SQLite artifacts.

Simulated lifecycle changes remain in memory; never checkpoint or move media.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from app.sqlite_isolated_adapter import inspect_isolated_audit_state
from app.sqlite_lifecycle_cycles import simulate_lifecycle_cycles


def rehearse_cycles_from_snapshot(
    source_json: str | Path,
    backup_json: str | Path,
    database: str | Path,
    *,
    media_key: str,
    initial_stage: str,
    cycles: list[dict[str, Any]],
    favorites_trigger_keep: bool = True,
) -> dict[str, Any]:
    """Verify persisted baseline, simulate cycles, and verify it again.

    This is deliberately NOT persistence of simulated transitions: filesystem
    moves and authoritative tracking checkpoints are still disabled.
    """
    before = inspect_isolated_audit_state(source_json, backup_json, database)
    simulation = simulate_lifecycle_cycles(
        before["state"],
        media_key=media_key,
        initial_stage=initial_stage,
        cycles=cycles,
        favorites_trigger_keep=favorites_trigger_keep,
    )
    after = inspect_isolated_audit_state(source_json, backup_json, database)
    if before != after:
        raise RuntimeError("SQLite baseline changed during read-only rehearsal")
    return {
        "baseline_revision": before["revision"],
        "history": simulation["history"],
        "final_stage": simulation["final_stage"],
        "simulated_state": simulation["simulated_state"],
        "persisted_state_unchanged": True,
        "authorization": "not_authorized",
        "persistence": "none",
        "production_activation": "disabled",
        "storage_authority": "json",
    }
