"""Safe, structured diagnostics for experimental SQLite recovery.

A blocked inspection is a normal outcome. This module translates expected
read-only inspection failures into stable operator-facing reasons without
leaking service URLs, credentials, filesystem paths, or response bodies.
It never clears intents, performs operations, or activates SQLite storage.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_http_recovery import inspect_http_recovery
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.state_store import GuardedSQLiteStateStore

# Explicit allowlist: do not put arbitrary exception text into a dashboard.
BLOCKERS = {
    "Jellyfin protection information incomplete": "jellyfin_scope_incomplete",
    "Jellyfin protection information unavailable": "jellyfin_unavailable",
    "Jellyfin protection information invalid": "jellyfin_invalid",
    "Recovery Jellyfin season enumeration incomplete": "season_list_incomplete",
    "Recovery Jellyfin season ownership mismatch": "season_identity_mismatch",
    "Recovery Jellyfin season identities ambiguous": "season_identity_ambiguous",
    "Recovery Jellyfin season set changed during inspection": "season_list_changed",
    "Recovery Jellyfin user set changed during inspection": "user_list_changed",
    "Recovery Jellyfin duplicate user identity": "duplicate_jellyfin_user",
    "Recovery Jellyfin users unavailable": "jellyfin_users_unavailable",
    "Recovery Jellyfin identity mismatch": "jellyfin_identity_mismatch",
    "Recovery Jellyfin tags unavailable": "jellyfin_tags_unavailable",
    "Recovery Jellyfin favorite unavailable": "jellyfin_favorite_unavailable",
    "Recovery service read failed": "service_read_failed",
    "Recovery service returned invalid data": "service_response_invalid",
    "Recovery response is stale or future-dated": "observation_not_fresh",
    "Recovery Arr credentials unavailable": "arr_credentials_missing",
    "Recovery Arr response identity mismatch": "arr_identity_mismatch",
    "Recovery requires explicit Jellyfin media type": "media_type_missing",
    "Recovery requires Jellyfin item identity": "jellyfin_identity_missing",
    "Recovery Arr fetcher unavailable": "arr_fetcher_missing",
}


def inspect_http_recovery_report(
    database: str | Path, **connection: Any,
) -> dict[str, Any]:
    """Return a safe blocked report; reject races and invalid persisted state.

    An unreadable or concurrently modified database is an exception, not a
    benign report. This distinction avoids masking an unsafe recovery race.
    """
    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    state, revision = session.read_verified_snapshot()
    pending = state.get(INTENTS_KEY)
    if not isinstance(pending, dict):
        raise RuntimeError("Pending recovery operation unavailable")
    operation_id = pending.get("id")
    phase = pending.get("phase")
    kind = pending.get("kind")
    if (not isinstance(operation_id, str) or not operation_id
            or phase not in ("intent_recorded", "applied_pending_reconciliation")
            or kind not in ("move", "arr_sync")):
        raise RuntimeError("Pending recovery operation invalid")

    result = {
        "operation_id": operation_id,
        "operation_kind": kind,
        "operation_phase": phase,
        "revision": revision,
        "storage_authority": "json",
        "production_activation": "disabled",
        "authorization": "blocked_pending_independent_verification",
    }
    try:
        details = inspect_http_recovery(database, **connection)
    except RuntimeError as exc:
        # Never swallow a stale session or failed checkpoint. Do not expose
        # unrecognized exception text (it may contain secrets).
        session.read_verified_snapshot()
        message = str(exc)
        if "stale" in message or "checkpoint" in message:
            raise
        return {**result, "status": "blocked",
                "blocker": BLOCKERS.get(message, "inspection_failed")}
    session.read_verified_snapshot()
    return {**result, "status": "blocked",
            "blocker": "reconciliation_not_authorized",
            "observation": details.get("observation"),
            "jellyfin_protection": details.get("jellyfin_protection")}
