"""Combine independently read filesystem and service diagnostics safely.

This report is observational only. Even agreeing evidence never grants
reconciliation, replay, move, deletion, or production activation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.sqlite_recovery_filesystem import inspect_pending_move_filesystem
from app.sqlite_recovery_report import inspect_http_recovery_report, inspect_pending_recovery_status


def inspect_combined_move_recovery(database: str | Path, **connection: Any) -> dict[str, Any]:
    """Combine allowlisted evidence; reject a changing SQLite revision."""
    before = inspect_pending_recovery_status(database)
    if before["status"] != "blocked" or before["operation_kind"] != "move":
        raise RuntimeError("Pending move unavailable")
    filesystem = inspect_pending_move_filesystem(database)
    if filesystem["revision"] != before["revision"]:
        raise RuntimeError("SQLite recovery session is stale")
    service = inspect_http_recovery_report(database, **connection)
    after = inspect_pending_recovery_status(database)
    if (after["revision"] != before["revision"]
            or after["status"] != "blocked"
            or after["operation_id"] != before["operation_id"]
            or after["operation_kind"] != before["operation_kind"]
            or service["revision"] != before["revision"]
            or service["operation_id"] != before["operation_id"]):
        raise RuntimeError("SQLite recovery session is stale")
    return {
        "revision": before["revision"],
        "status": "blocked",
        "authorization": "not_authorized",
        "operation_kind": "move",
        "filesystem": {
            "source_status": filesystem["source_status"],
            "destination_status": filesystem["destination_status"],
            "interpretation": filesystem["interpretation"],
        },
        "service": {
            "status": service["status"],
            "blocker": service["blocker"],
        },
        "external_verification": "incomplete",
        "reconciliation": "disabled",
    }
