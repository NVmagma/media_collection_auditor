"""Offline opt-in orchestration of read-only identity and filesystem evidence.

Never grants reconciliation or changes the persisted pending operation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_recovery_filesystem import inspect_pending_move_filesystem
from app.sqlite_recovery_http import ReadOnlyRecoveryHTTP
from app.sqlite_recovery_identity import inspect_fetched_move_identity
from app.sqlite_recovery_path_binding import inspect_move_path_binding
from app.state_store import GuardedSQLiteStateStore


def inspect_live_move_identity(database: str | Path, **connection: Any) -> dict[str, Any]:
    """Inspect authenticated service identities against one stable move intent."""
    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    state, revision = session.read_verified_snapshot()
    pending = state.get(INTENTS_KEY)
    if (not isinstance(pending, dict) or pending.get("kind") != "move"
            or pending.get("phase") not in
            ("intent_recorded", "applied_pending_reconciliation")
            or not isinstance(pending.get("details"), dict)):
        raise RuntimeError("Pending move unavailable")
    intent = pending["details"]
    media_type = intent.get("jellyfin_type")
    jellyfin_id = intent.get("jellyfin_item_id")
    arr_id = intent.get("arr_title_id")
    if (media_type not in ("Movie", "Series") or not isinstance(jellyfin_id, str)
            or not jellyfin_id or type(arr_id) is not int or arr_id <= 0):
        raise RuntimeError("Pending move identity invalid")
    filesystem = inspect_pending_move_filesystem(database)
    if filesystem["revision"] != revision:
        raise RuntimeError("SQLite recovery session is stale")
    adapter = ReadOnlyRecoveryHTTP(**connection)
    service = "radarr" if media_type == "Movie" else "sonarr"
    binding = {"path_binding": "unverified", "reason": "service_inspection_failed"}
    try:
        jellyfin = adapter.jellyfin_fetch_identity(jellyfin_id)
        arr = adapter.arr_fetch(service, arr_id)
        identity = inspect_fetched_move_identity(
            intent, jellyfin_response=jellyfin, arr_response=arr,
        )
        # Path agreement is not meaningful when identity or freshness fails.
        if identity["identity_verification"] == "consistent_not_authoritative":
            binding = inspect_move_path_binding(
                intent, jellyfin_record=jellyfin.get("data"),
                arr_record=arr.get("data"),
                filesystem_interpretation=filesystem["interpretation"],
            )
        else:
            binding = {"path_binding": "unverified",
                       "reason": "identity_not_consistent"}
    except RuntimeError as exc:
        # Never expose service URLs, response bodies or credentials.
        identity = {"status": "blocked", "authorization": "not_authorized",
                    "identity_verification": "incomplete",
                    "reason": "service_inspection_failed"}
    # Always verify the persisted snapshot again, including on service errors.
    session.read_verified_snapshot()
    return {
        "revision": revision,
        "status": "blocked",
        "authorization": "not_authorized",
        "filesystem_interpretation": filesystem["interpretation"],
        "identity_verification": identity["identity_verification"],
        "identity_reason": identity["reason"],
        "path_binding": binding["path_binding"],
        "path_binding_reason": binding["reason"],
        "external_verification": "incomplete",
        "reconciliation": "disabled",
    }
