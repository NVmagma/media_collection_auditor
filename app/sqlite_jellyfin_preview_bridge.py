"""Read-only bridge from experimental Jellyfin collection to SQLite previews.

This bridge does not attest to Jellyfin freshness, authorize a move, or
replace the production JSON auditor. A failed collection contributes no
signals, so the lifecycle preview fails closed for that title.
"""

from __future__ import annotations

from app.sqlite_collection_decision_preview import preview_collection
from app.sqlite_jellyfin_collection import collect_title_observation


def preview_with_collected_jellyfin(*, database, now, thresholds, requests,
                                   fetch, favorites_trigger_keep=True):
    """Collect each requested title, then preview without side effects.

    requests maps the SQLite media key to {"jellyfin_type", "folder"}.
    A missing request is not interpreted as an unprotected title.
    """
    if not isinstance(requests, dict):
        raise ValueError("Title requests mapping required")
    signals = {}
    observations = {}
    for media_key, details in requests.items():
        if not isinstance(media_key, str) or not media_key or not isinstance(details, dict):
            raise ValueError("Invalid title collection request")
        result = collect_title_observation(
            fetch=fetch, jellyfin_type=details.get("jellyfin_type"),
            folder=details.get("folder"), media_key=media_key, now=now)
        observations[media_key] = {
            "status": result["status"],
            "blockers": list(result["blockers"]),
        }
        if result["status"] == "shape_valid_untrusted":
            signals[media_key] = result["signals"]
    preview = preview_collection(
        database=database, now=now, thresholds=thresholds,
        signals_by_key=signals,
        favorites_trigger_keep=favorites_trigger_keep)
    return {
        "status": "blocked" if (any(value["status"] == "blocked"
                                    for value in observations.values())
                                or preview["blocked_titles"]) else "advisory_only",
        "observations": observations,
        "preview": preview,
        "authorization": "not_authorized",
        "production_activation": "disabled",
        "freshness_independently_verified": False,
        "read_only": True,
    }
