"""Read-only filesystem evidence for an interrupted SQLite move.

This diagnostic cannot authorize reconciliation. It never follows symbolic
links, modifies files, or assumes that a destination's existence proves a move.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.state_store import GuardedSQLiteStateStore


def _inspect_directory(raw: Any) -> str:
    if not isinstance(raw, str) or not raw or not os.path.isabs(raw):
        return "invalid_path"
    path = Path(raw)
    # Do not resolve() or traverse symlinked ancestors: their targets could
    # change during inspection and must never be treated as verified.
    try:
        components = path.parts
        current = Path(components[0])
        for component in components[1:]:
            current = current / component
            if current.is_symlink():
                return "symlink_unsafe"
        if not path.exists():
            return "missing"
        if not path.is_dir():
            return "not_directory"
        return "present"
    except (OSError, ValueError):
        return "unavailable"


def inspect_pending_move_filesystem(database: str | Path) -> dict[str, Any]:
    """Inspect two directories without mutating state or claiming success."""
    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    state, revision = session.read_verified_snapshot()
    pending = state.get(INTENTS_KEY)
    if not isinstance(pending, dict) or pending.get("kind") != "move":
        raise RuntimeError("Pending move unavailable")
    if pending.get("phase") not in (
        "intent_recorded", "applied_pending_reconciliation"
    ):
        raise RuntimeError("Pending move phase invalid")
    details = pending.get("details")
    if not isinstance(details, dict):
        raise RuntimeError("Pending move details invalid")
    source, destination = details.get("source"), details.get("destination")
    if not isinstance(source, str) or not isinstance(destination, str):
        raise RuntimeError("Pending move paths invalid")
    if source == destination:
        raise RuntimeError("Pending move paths identical")
    source_status = _inspect_directory(source)
    destination_status = _inspect_directory(destination)
    # Confirm SQLite did not change while filesystem was observed.
    session.read_verified_snapshot()
    # A second observation detects simple mid-inspection changes. This does
    # not provide an atomic filesystem snapshot or eliminate TOCTOU races.
    if (_inspect_directory(source) != source_status
            or _inspect_directory(destination) != destination_status):
        source_status = "unavailable"
        destination_status = "unavailable"
    if source_status == "present" and destination_status == "missing":
        interpretation = "source_only"
    elif source_status == "missing" and destination_status == "present":
        interpretation = "destination_only_unverified"
    elif source_status == "present" and destination_status == "present":
        interpretation = "both_present_ambiguous"
    elif source_status == "missing" and destination_status == "missing":
        interpretation = "both_missing"
    else:
        interpretation = "inspection_incomplete"
    return {
        "revision": revision,
        "status": "blocked",
        "authorization": "not_authorized",
        "source_status": source_status,
        "destination_status": destination_status,
        "interpretation": interpretation,
        "external_verification": "filesystem_only_incomplete",
    }
