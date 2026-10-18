"""End-to-end read-only recovery from live service adapters.

All service observations are diagnostic. Incomplete Jellyfin scope must
never authorize a checkpoint, a replay, or an intent clearance.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from app.sqlite_fetched_recovery import inspect_fetched_recovery
from app.sqlite_recovery_http import ReadOnlyRecoveryHTTP


def inspect_http_recovery(
    database: str | Path,
    *,
    jellyfin_url: str,
    jellyfin_token: str,
    jellyfin_user_id: str,
    radarr_url: str = "",
    radarr_key: str = "",
    sonarr_url: str = "",
    sonarr_key: str = "",
    http: Any = None,
) -> dict[str, Any]:
    """Use authenticated read-only service clients; never mutate state.

    Unlike the generic fetched-evidence inspector, this entry point does not
    accept caller-supplied proof of complete Jellyfin protection. Series
    seasons are enumerated from Jellyfin; movies check all users. Neither
    observation is transactional, so the strict completeness gate blocks
    reconciliation until a safe authorization protocol exists.
    """
    kwargs = {
        "jellyfin_url": jellyfin_url,
        "jellyfin_token": jellyfin_token,
        "jellyfin_user_id": jellyfin_user_id,
        "radarr_url": radarr_url,
        "radarr_key": radarr_key,
        "sonarr_url": sonarr_url,
        "sonarr_key": sonarr_key,
    }
    if http is not None:
        kwargs["http"] = http
    adapter = ReadOnlyRecoveryHTTP(**kwargs)

    # Import inside the entry point so no production runtime is imported.
    from app.sqlite_audit_session import RevisionedAuditSession
    from app.sqlite_operation_coordinator import INTENTS_KEY
    from app.state_store import GuardedSQLiteStateStore

    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    state, revision = session.read_verified_snapshot()
    pending = state.get(INTENTS_KEY)
    if not isinstance(pending, dict) or not isinstance(pending.get("details"), dict):
        raise RuntimeError("Pending recovery operation unavailable")
    details = pending["details"]
    item_id = details.get("jellyfin_item_id")
    media_type = details.get("jellyfin_type")
    if not isinstance(item_id, str) or not item_id:
        raise RuntimeError("Recovery requires Jellyfin item identity")
    if media_type not in ("Movie", "Series"):
        raise RuntimeError("Recovery requires explicit Jellyfin media type")

    fetch = (adapter.jellyfin_fetch_verified_series if media_type == "Series"
             else adapter.jellyfin_fetch_all_users)
    try:
        return inspect_fetched_recovery(
            database,
            jellyfin_fetch=fetch,
            arr_fetch=adapter.arr_fetch,
            max_age=timedelta(seconds=30),
        )
    finally:
        # If another writer intervened while fetching, never report a clean
        # recovery result to a caller, even when service inspection failed.
        session.read_verified_snapshot()
