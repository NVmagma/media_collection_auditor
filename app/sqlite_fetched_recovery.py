"""Read-only, independently fetched recovery observations.

Fetchers are injected adapters, not caller-provided evidence dictionaries.
Adapters must authenticate the remote service and return a response tied to
the requested title. This module never authorizes intent clearance.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_combined_recovery import inspect_combined_recovery
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.state_store import GuardedSQLiteStateStore


def _fresh_response(
    response: dict[str, Any], *, service: str, title_id: str,
    now: datetime, max_age: timedelta,
) -> dict[str, Any]:
    if not isinstance(response, dict):
        raise RuntimeError("Recovery service response unavailable")
    if response.get("service") != service or response.get("title_id") != title_id:
        raise RuntimeError("Recovery response identity mismatch")
    observed = response.get("observed_at")
    if not isinstance(observed, datetime) or observed.tzinfo is None:
        raise RuntimeError("Recovery response timestamp unavailable")
    age = now - observed.astimezone(timezone.utc)
    if age < timedelta(0) or age > max_age:
        raise RuntimeError("Recovery response is stale or future-dated")
    data = response.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("Recovery response data unavailable")
    return data


def inspect_fetched_recovery(
    database: str | Path,
    *,
    jellyfin_fetch: Callable[[str], dict[str, Any]],
    arr_fetch: Callable[[str, int], dict[str, Any]] | None = None,
    now: datetime | None = None,
    max_age: timedelta = timedelta(seconds=30),
) -> dict[str, Any]:
    """Inspect a persisted intent using independently fetched, bounded evidence.

    The pending operation must carry a stable Jellyfin item identity. Fetchers
    are expected to use authenticated service APIs, not cached caller inputs.
    """
    if max_age <= timedelta(0) or max_age > timedelta(minutes=5):
        raise RuntimeError("Recovery freshness window invalid")
    if now is not None and now.tzinfo is None:
        raise RuntimeError("Recovery clock must be timezone-aware")
    if now is not None:
        now = now.astimezone(timezone.utc)
    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    state, revision = session.read_verified_snapshot()
    pending = state.get(INTENTS_KEY)
    if not isinstance(pending, dict) or not isinstance(pending.get("details"), dict):
        raise RuntimeError("Pending recovery operation unavailable")
    details = pending["details"]
    jellyfin_id = details.get("jellyfin_item_id")
    if not isinstance(jellyfin_id, str) or not jellyfin_id:
        raise RuntimeError("Recovery requires Jellyfin item identity")
    jellyfin = _fresh_response(
        jellyfin_fetch(jellyfin_id), service="jellyfin",
        title_id=jellyfin_id, now=now or datetime.now(timezone.utc), max_age=max_age,
    )
    arr_record = None
    if pending.get("kind") == "arr_sync":
        service, title_id = details.get("service"), details.get("title_id")
        if service not in ("radarr", "sonarr") or type(title_id) is not int or title_id <= 0:
            raise RuntimeError("Recovery Arr identity invalid")
        if arr_fetch is None:
            raise RuntimeError("Recovery Arr fetcher unavailable")
        arr_record = _fresh_response(
            arr_fetch(service, title_id), service=service,
            title_id=str(title_id), now=now or datetime.now(timezone.utc), max_age=max_age,
        )
    elif pending.get("kind") != "move":
        raise RuntimeError("Recovery operation unsupported")
    report = inspect_combined_recovery(
        state, jellyfin_evidence=jellyfin, arr_record=arr_record
    )
    session.read_verified_snapshot()
    return {
        **report, "revision": revision,
        "storage_authority": "json",
        "production_activation": "disabled",
        "authorization": "blocked_pending_independent_verification",
    }
