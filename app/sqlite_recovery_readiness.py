"""Conservative readiness assessment for experimental SQLite recovery.

This is an advisory report, not authorization to clear an intent. It relies
only on the sanitized offline status and never touches external services.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.sqlite_recovery_report import inspect_pending_recovery_status


def inspect_recovery_readiness(database: str | Path) -> dict[str, Any]:
    """Return a fixed checklist with no sensitive operation details."""
    report = inspect_pending_recovery_status(database)
    return recovery_readiness_from_report(report)


def recovery_readiness_from_report(report: dict[str, Any]) -> dict[str, Any]:
    """Derive a checklist from the same verified snapshot as the status view."""
    status = report["status"]
    if status not in ("blocked", "no_pending_operation"):
        raise RuntimeError("Recovery status invalid")
    pending = status == "blocked"
    return {
        "status": status,
        "storage_authority": "json",
        "production_activation": "disabled",
        "recovery_clearance": "not_authorized",
        "checks": [
            {
                "id": "sqlite_snapshot",
                "status": "verified",
                "detail": "A consistent SQLite snapshot was readable.",
            },
            {
                "id": "pending_intent",
                "status": "blocked" if pending else "clear",
                "detail": (
                    "An interrupted operation requires independent verification."
                    if pending else "No pending operation was recorded."
                ),
            },
            {
                "id": "external_verification",
                "status": "not_performed",
                "detail": "Filesystem, Jellyfin and Arr were not inspected.",
            },
            {
                "id": "automatic_reconciliation",
                "status": "disabled",
                "detail": "No operation may be replayed or cleared automatically.",
            },
            {
                "id": "production_cutover",
                "status": "not_approved",
                "detail": "JSON remains the authoritative production state.",
            },
        ],
    }
