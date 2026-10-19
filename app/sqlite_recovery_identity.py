"""Conservative, read-only cross-service identity diagnostics for move recovery.

Paths and IDs are not interchangeable proof. A matching Arr identifier alone
does not establish Jellyfin identity or authorize reconciliation.
"""

from __future__ import annotations

from pathlib import PurePath
from typing import Any


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
