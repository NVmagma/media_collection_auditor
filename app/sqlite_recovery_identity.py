"""Conservative, read-only cross-service identity diagnostics for move recovery.

Paths and IDs are not interchangeable proof. A matching Arr identifier alone
does not establish Jellyfin identity or authorize reconciliation.
"""

from __future__ import annotations

from typing import Any
from datetime import datetime, timedelta, timezone


def inspect_move_identity(
    intent: dict[str, Any],
    *,
    jellyfin: dict[str, Any] | None,
    arr: dict[str, Any] | None,
) -> dict[str, str]:
    """Classify independently observed identifiers without exposing their values."""
    result = {"status": "blocked", "authorization": "not_authorized",
              "identity_verification": "incomplete"}
    if not isinstance(intent, dict) or not isinstance(jellyfin, dict) or not isinstance(arr, dict):
        return {**result, "reason": "missing_evidence"}
    item_id = intent.get("jellyfin_item_id")
    media_type = intent.get("jellyfin_type")
    if not isinstance(item_id, str) or not item_id or media_type not in ("Movie", "Series"):
        return {**result, "reason": "invalid_intent_identity"}
    if jellyfin.get("Id") != item_id or jellyfin.get("Type") != media_type:
        return {**result, "reason": "jellyfin_identity_mismatch"}
    service = "radarr" if media_type == "Movie" else "sonarr"
    if arr.get("service") != service:
        return {**result, "reason": "arr_service_mismatch"}
    expected_arr_id = intent.get("arr_title_id")
    record = arr.get("record")
    if type(expected_arr_id) is not int or expected_arr_id <= 0:
        return {**result, "reason": "arr_identity_missing"}
    if not isinstance(record, dict) or type(record.get("id")) is not int or record["id"] != expected_arr_id:
        return {**result, "reason": "arr_identity_mismatch"}
    # Both services have different namespaces. Require an independently
    # recorded shared external ID rather than comparing Jellyfin and Arr IDs.
    external_id = intent.get("external_id")
    if not isinstance(external_id, str) or not external_id:
        return {**result, "reason": "shared_identity_missing"}
    key = "imdbId" if media_type == "Movie" else "tvdbId"
    if media_type == "Series":
        if not external_id.isdecimal() or type(record.get(key)) is not int:
            return {**result, "reason": "shared_identity_invalid"}
        matches = str(record[key]) == external_id
        jf_id = jellyfin.get("ProviderIds", {}).get("Tvdb") if isinstance(jellyfin.get("ProviderIds"), dict) else None
    else:
        matches = record.get(key) == external_id
        jf_id = jellyfin.get("ProviderIds", {}).get("Imdb") if isinstance(jellyfin.get("ProviderIds"), dict) else None
    if not matches or jf_id != external_id:
        return {**result, "reason": "shared_identity_mismatch"}
    # This is only an identity consistency observation, not a trusted
    # transactional snapshot of filesystem or protection information.
    return {**result, "reason": "identifiers_consistent_unverified",
            "identity_verification": "consistent_not_authoritative"}


def inspect_fetched_move_identity(
    intent: dict[str, Any],
    *,
    jellyfin_response: dict[str, Any] | None,
    arr_response: dict[str, Any] | None,
    now: datetime | None = None,
    max_age: timedelta = timedelta(seconds=30),
) -> dict[str, str]:
    """Validate independently fetched envelopes before comparing identities.

    Fetchers must authenticate their own remote reads. An envelope is not
    evidence of a transactionally consistent filesystem or protection state.
    """
    blocked = {"status": "blocked", "authorization": "not_authorized",
               "identity_verification": "incomplete"}
    if not isinstance(intent, dict):
        return {**blocked, "reason": "invalid_intent_identity"}
    if max_age <= timedelta(0) or max_age > timedelta(minutes=5):
        return {**blocked, "reason": "invalid_freshness_window"}
    current = now if now is not None else datetime.now(timezone.utc)
    if not isinstance(current, datetime) or current.tzinfo is None:
        return {**blocked, "reason": "invalid_clock"}
    expected_type = intent.get("jellyfin_type")
    expected_service = {"Movie": "radarr", "Series": "sonarr"}.get(expected_type)
    expected_id = intent.get("jellyfin_item_id")
    expected_arr_id = intent.get("arr_title_id")
    if (expected_service is None or not isinstance(expected_id, str)
            or not expected_id or type(expected_arr_id) is not int
            or expected_arr_id <= 0):
        return {**blocked, "reason": "invalid_intent_identity"}
    for envelope, service, title_id in (
        (jellyfin_response, "jellyfin", expected_id),
        (arr_response, expected_service, str(expected_arr_id)),
    ):
        if not isinstance(envelope, dict):
            return {**blocked, "reason": "missing_evidence"}
        if envelope.get("service") != service or envelope.get("title_id") != title_id:
            return {**blocked, "reason": "response_identity_mismatch"}
        observed = envelope.get("observed_at")
        if not isinstance(observed, datetime) or observed.tzinfo is None:
            return {**blocked, "reason": "observation_timestamp_missing"}
        age = current.astimezone(timezone.utc) - observed.astimezone(timezone.utc)
        if age < timedelta(0) or age > max_age:
            return {**blocked, "reason": "observation_not_fresh"}
    jf_data = jellyfin_response.get("data")
    arr_data = arr_response.get("data")
    if not isinstance(jf_data, dict) or not isinstance(arr_data, dict):
        return {**blocked, "reason": "response_data_invalid"}
    return inspect_move_identity(
        intent, jellyfin=jf_data,
        arr={"service": expected_service, "record": arr_data},
    )
