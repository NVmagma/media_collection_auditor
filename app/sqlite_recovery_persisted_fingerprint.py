"""Read-only inspection of persisted experimental pre-move evidence.

A matching directory fingerprint is advisory only. Inode reuse, container
mount differences, cross-device copies and races prevent recovery clearance.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_recovery_fingerprint import (
    capture_directory_fingerprint, compare_directory_fingerprint,
)
from app.sqlite_recovery_pre_move_evidence import validate_pre_move_evidence
from app.state_store import GuardedSQLiteStateStore


def inspect_persisted_move_evidence(database: str | Path) -> dict[str, Any]:
    """Inspect source and destination metadata against one stable SQLite intent."""
    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    state, revision = session.read_verified_snapshot()
    pending = state.get(INTENTS_KEY)
    if (not isinstance(pending, dict) or pending.get("kind") != "move"
            or pending.get("phase") not in (
                "intent_recorded", "applied_pending_reconciliation"
            ) or not isinstance(pending.get("details"), dict)):
        raise RuntimeError("Pending move unavailable")
    details = pending["details"]
    evidence = details.get("pre_move_evidence")
    validation = validate_pre_move_evidence(evidence)
    result = {
        "revision": revision,
        "status": "blocked",
        "authorization": "not_authorized",
        "evidence_verification": validation["evidence_verification"],
        "evidence_reason": validation["reason"],
        "source_fingerprint": "unverified",
        "source_reason": "evidence_unavailable",
        "destination_fingerprint": "unverified",
        "destination_reason": "evidence_unavailable",
        "reconciliation": "disabled",
    }
    if validation["evidence_verification"] == "schema_valid_untrusted":
        fingerprint = evidence["fingerprint"]
        for label, path_key in (("source", "source"), ("destination", "destination")):
            observed = capture_directory_fingerprint(details.get(path_key))
            comparison = compare_directory_fingerprint(fingerprint, observed)
            result[f"{label}_fingerprint"] = comparison["fingerprint_binding"]
            result[f"{label}_reason"] = comparison["reason"]
    # A stale or tampered snapshot is never reported as a benign mismatch.
    session.read_verified_snapshot()
    return result
