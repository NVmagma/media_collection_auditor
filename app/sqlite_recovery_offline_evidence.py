"""Consolidated offline SQLite recovery evidence, never clearance.

Both inspectors read independently. Require matching operation and revision
before presenting evidence together; no external actions are performed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.sqlite_recovery_report import inspect_pending_recovery_status
from app.sqlite_recovery_filesystem import inspect_pending_move_filesystem
from app.sqlite_recovery_decision_matrix import classify_move_recovery
from app.sqlite_recovery_persisted_fingerprint import inspect_persisted_move_evidence


def inspect_offline_move_evidence(database: str | Path) -> dict[str, Any]:
    """Return allowlisted evidence only when one pending move stays stable."""
    before = inspect_pending_recovery_status(database)
    if before.get("status") != "blocked" or before.get("operation_kind") != "move":
        raise RuntimeError("Pending move unavailable")
    fingerprint = inspect_persisted_move_evidence(database)
    filesystem = inspect_pending_move_filesystem(database)
    after = inspect_pending_recovery_status(database)
    if (after.get("revision") != before.get("revision")
            or after.get("operation_id") != before.get("operation_id")
            or after.get("operation_kind") != "move"
            or after.get("operation_phase") != before.get("operation_phase")
            or after.get("status") != "blocked"
            or filesystem.get("revision") != before.get("revision")
            or filesystem.get("status") != "blocked"
            or filesystem.get("authorization") != "not_authorized"
            or fingerprint.get("revision") != before.get("revision")
            or fingerprint.get("status") != "blocked"
            or fingerprint.get("authorization") != "not_authorized"):
        raise RuntimeError("SQLite recovery session is stale")
    interpretations = {
        "source_only": "source_only",
        "destination_only_unverified": "destination_only_unverified",
        "both_present_ambiguous": "both_present",
        "both_missing": "both_missing",
        "inspection_incomplete": "unavailable",
    }
    decision = classify_move_recovery(
        filesystem=interpretations.get(filesystem.get("interpretation"), "invalid"),
        identity="incomplete",  # No live service reads in this offline report.
        evidence=fingerprint["evidence_verification"],
        source_fingerprint=fingerprint["source_fingerprint"],
        destination_fingerprint=fingerprint["destination_fingerprint"],
        mount_binding="unverified",  # Container mount roots not verified.
        cross_device="unknown",  # No trusted pre-move device proof.
    )
    return {
        "revision": before["revision"],
        "status": "blocked",
        "authorization": "not_authorized",
        "operation_kind": "move",
        "evidence": {
            "verification": fingerprint["evidence_verification"],
            "reason": fingerprint["evidence_reason"],
            "source": fingerprint["source_fingerprint"],
            "source_reason": fingerprint["source_reason"],
            "destination": fingerprint["destination_fingerprint"],
            "destination_reason": fingerprint["destination_reason"],
        },
        "filesystem_interpretation": filesystem.get("interpretation"),
        "decision": decision,
        "external_verification": "incomplete",
        "reconciliation": "disabled",
        "storage_authority": "json",
        "production_activation": "disabled",
    }
