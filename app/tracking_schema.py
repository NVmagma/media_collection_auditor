"""Validate lifecycle tracking snapshots without changing saved dates."""
from __future__ import annotations
import datetime
from typing import Any

SECTIONS = ("first_seen", "queued", "in_removal", "keep_seen", "arr_sync_pending")

def validate_snapshot(state: dict[str, dict[str, Any]]) -> None:
    """Apply the auditor's existing lifecycle and Arr retry invariants.

    This is intentionally independent of the production JSON loader; the
    auditor continues to use that loader until migration is explicitly enabled.
    """
    if not isinstance(state, dict) or any(
        section not in state or not isinstance(state[section], dict)
        for section in SECTIONS
    ):
        raise RuntimeError("tracking snapshot has missing or invalid state sections")
    now = datetime.datetime.now()
    for section in SECTIONS[:-1]:
        for key, timestamp in state[section].items():
            if not isinstance(key, str) or not key or not isinstance(timestamp, str):
                raise RuntimeError(f"Invalid {section} state entry")
            try:
                parsed = datetime.datetime.fromisoformat(timestamp)
            except ValueError as exc:
                raise RuntimeError(f"Invalid {section} timestamp") from exc
            if parsed.tzinfo is not None or parsed > now:
                raise RuntimeError(f"Unsafe {section} timestamp")
    for key, entry in state["arr_sync_pending"].items():
        if (not isinstance(key, str) or not key or not isinstance(entry, dict)
                or entry.get("stage") not in ("holding", "keep", "removal")
                or not isinstance(entry.get("root"), str) or not entry["root"]
                or (entry.get("monitored") is not None
                    and type(entry["monitored"]) is not bool)):
            raise RuntimeError("Invalid Arr retry entry")
