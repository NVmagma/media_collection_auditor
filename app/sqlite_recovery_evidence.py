"""Fail-closed evidence evaluation for interrupted SQLite operations.

This diagnostic gate does not mutate SQLite, touch media, or call external
services. Matching observations are not proof of Jellyfin protection state,
so the result always requires a separate authorization step.
"""

from __future__ import annotations

from typing import Any

from app.sqlite_arr_reconciliation import inspect_arr_sync
from app.sqlite_move_reconciliation import inspect_move_intent
from app.sqlite_operation_coordinator import INTENTS_KEY


def evaluate_recovery_evidence(
    state: dict[str, Any],
    *,
    arr_record: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Evaluate only a recorded intent; never authorize automatic clearance."""
    if not isinstance(state, dict):
        raise RuntimeError("SQLite recovery state is invalid")
    pending = state.get(INTENTS_KEY)
    if not isinstance(pending, dict):
        raise RuntimeError("Pending SQLite operation is missing")
    kind = pending.get("kind")
    phase = pending.get("phase")
    operation_id = pending.get("id")
    details = pending.get("details")
    if (not isinstance(operation_id, str) or not operation_id
            or phase not in ("intent_recorded", "applied_pending_reconciliation")
            or not isinstance(details, dict)):
        raise RuntimeError("Malformed SQLite operation intent")
    if kind == "move":
        if arr_record is not None:
            raise RuntimeError("Unexpected Arr evidence for filesystem move")
        observation = inspect_move_intent(details)
    elif kind == "arr_sync":
        observation = inspect_arr_sync(details, arr_record)
    else:
        raise RuntimeError("Unsupported SQLite recovery operation")
    return {
        "id": operation_id,
        "kind": kind,
        "phase": phase,
        "observation": observation,
        "authorization": "blocked_pending_independent_verification",
    }
