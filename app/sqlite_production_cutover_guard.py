"""Read-only SQLite cutover assessment; NEVER authorizes production activation.

This module deliberately has no filesystem writes, media moves, or imports
of the production audit runner. The JSON backend remains authoritative.
"""

from __future__ import annotations

from pathlib import Path

from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_state import SECTIONS, validate_snapshot
from app.state_store import GuardedSQLiteStateStore


def assess_sqlite_cutover(*, database, json_state, stage_roots,
                          jellyfin_protection_available=False,
                          external_integrations_verified=False):
    """Return explicit blockers; never enable SQLite based on this report."""
    blockers = ["sqlite_production_activation_not_approved"]
    if not isinstance(json_state, dict):
        blockers.append("json_tracking_unavailable")
    else:
        try:
            validate_snapshot(json_state)
        except Exception:
            blockers.append("json_tracking_invalid")
    if not isinstance(stage_roots, dict) or set(stage_roots) != {
            "transient", "holding", "removal", "keep"}:
        blockers.append("stage_roots_incomplete")
    else:
        resolved = []
        for stage, path in stage_roots.items():
            try:
                path = Path(path)
                if not path.is_absolute() or path.is_symlink() or not path.is_dir():
                    raise ValueError("unsafe stage root")
                resolved.append(path.resolve())
            except (OSError, ValueError, TypeError):
                blockers.append(f"stage_root_unavailable:{stage}")
        if any(left == right or left in right.parents or right in left.parents
               for index, left in enumerate(resolved)
               for right in resolved[index + 1:]):
            blockers.append("stage_roots_overlap")
    try:
        sqlite_state, revision = GuardedSQLiteStateStore(database).load_with_revision()
        validate_snapshot(sqlite_state)
        if sqlite_state.get(INTENTS_KEY):
            blockers.append("sqlite_unresolved_operations")
        if isinstance(json_state, dict) and sqlite_state != json_state:
            blockers.append("json_sqlite_state_mismatch")
    except Exception:
        blockers.append("sqlite_snapshot_unavailable_or_invalid")
        revision = None
    if not jellyfin_protection_available:
        blockers.append("jellyfin_protection_unverified")
    if not external_integrations_verified:
        blockers.append("arr_dashboard_tv_integration_unverified")
    return {
        "status": "blocked",
        "production_activation": "disabled",
        "authorization": "not_authorized",
        "database_revision": revision,
        "blockers": blockers,
        "read_only": True,
    }
