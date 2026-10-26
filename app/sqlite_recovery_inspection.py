"""Read-only recovery report for pending SQLite operation intents.

Reports are diagnostic, not permission to replay, mark applied, or clear
an operation. No network requests, filesystem mutations, or DB writes.
"""

from __future__ import annotations

from typing import Any

from app.sqlite_move_reconciliation import inspect_move_intent
from app.sqlite_operation_coordinator import INTENTS_KEY


def inspect_pending_operation(state: dict[str, Any]) -> dict[str, str]:
    """Classify a pending intent without making any lifecycle decisions."""
    if not isinstance(state, dict):
        raise RuntimeError("SQLite recovery state is invalid")
    pending = state.get(INTENTS_KEY)
    if not isinstance(pending, dict):
        raise RuntimeError("No valid pending SQLite operation to inspect")
    operation_id = pending.get("id")
    kind = pending.get("kind")
    phase = pending.get("phase")
    details = pending.get("details")
    if (not isinstance(operation_id, str) or not operation_id
            or phase not in ("intent_recorded", "applied_pending_reconciliation")
            or not isinstance(details, dict)):
        raise RuntimeError("Malformed SQLite operation intent")
    if kind == "move":
        observation = inspect_move_intent(details)
        return {
            "id": operation_id,
            "kind": kind,
            "phase": phase,
            "observation": observation,
            "decision": "manual_reconciliation_required",
        }
    if kind == "arr_sync":
        return {
            "id": operation_id,
            "kind": kind,
            "phase": phase,
            "observation": "external_state_unverified",
            "decision": "manual_reconciliation_required",
        }
    if kind == "copy_stage":
        copy_phase = details.get("copy_phase")
        if copy_phase not in ("prepared", "verified_source_retained"):
            raise RuntimeError("Malformed copy staging phase")
        return {"id": operation_id, "kind": kind, "phase": phase,
                "observation": copy_phase, "decision": "manual_reconciliation_required"}
    raise RuntimeError("Unsupported SQLite recovery operation")
