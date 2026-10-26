"""Static operator guidance for experimental, blocked SQLite recovery.

Guidance is descriptive only: never interpret it as clearance to retry,
replay, delete, or change the stored intent.
"""

from __future__ import annotations

from typing import Any

GUIDANCE = {
    "independent_verification_required": (
        "An interrupted operation is still recorded.",
        "Compare the expected and actual media location and check Jellyfin and Arr manually. Do not replay or clear the operation.",
    ),
    "jellyfin_scope_incomplete": (
        "Jellyfin protection evidence is incomplete.",
        "Confirm all configured Jellyfin users and relevant seasons can be enumerated before any manual recovery decision.",
    ),
    "jellyfin_unavailable": (
        "Jellyfin protection evidence is unavailable.",
        "Restore Jellyfin connectivity and verify protection tags and favorites before proceeding.",
    ),
    "observation_not_fresh": (
        "Service evidence is too old or has an invalid timestamp.",
        "Collect fresh read-only observations and verify system clocks.",
    ),
    "inspection_failed": (
        "Recovery inspection could not be completed safely.",
        "Review service availability and application logs without sharing credentials; leave the pending operation unchanged.",
    ),
    "service_read_failed": (
        "A required service could not be read.",
        "Verify service connectivity and permissions. Do not infer that the media is unprotected.",
    ),
    "season_list_changed": (
        "Jellyfin seasons changed during inspection.",
        "Wait for Jellyfin library activity to settle, then inspect the full season list again.",
    ),
    "user_list_changed": (
        "Jellyfin users changed during inspection.",
        "Verify all Jellyfin users and their favorites before reviewing recovery.",
    ),
    "jellyfin_invalid": (
        "Jellyfin returned invalid protection information.",
        "Check the Jellyfin response and configured access before trusting tags or favorites.",
    ),
    "season_list_incomplete": (
        "Jellyfin did not return a complete season list.",
        "Verify every season in the series is represented before reviewing recovery.",
    ),
    "season_identity_mismatch": (
        "A Jellyfin season belongs to an unexpected series.",
        "Verify the series and season identities; do not reconcile ambiguous titles.",
    ),
    "season_identity_ambiguous": (
        "Jellyfin season identities are ambiguous.",
        "Resolve duplicate or missing season identities before any manual decision.",
    ),
    "duplicate_jellyfin_user": (
        "Duplicate Jellyfin user identities were observed.",
        "Verify the complete user list and favorites for each distinct user.",
    ),
    "jellyfin_users_unavailable": (
        "Jellyfin users could not be enumerated.",
        "Restore user enumeration before evaluating favorites or protection.",
    ),
    "jellyfin_identity_mismatch": (
        "The Jellyfin item identity did not match the expected title.",
        "Verify the exact item identity and media type without relying on the title alone.",
    ),
    "jellyfin_tags_unavailable": (
        "Jellyfin protection tags could not be verified.",
        "Restore tag visibility and confirm keep and permanent protection before proceeding.",
    ),
    "jellyfin_favorite_unavailable": (
        "Jellyfin favorites could not be verified.",
        "Check favorites for all relevant users before deciding an item is unprotected.",
    ),
    "service_response_invalid": (
        "A service returned invalid recovery evidence.",
        "Check the service response format and identity; leave the pending operation unchanged.",
    ),
    "arr_credentials_missing": (
        "Arr credentials are unavailable.",
        "Restore read-only Radarr or Sonarr access before verifying synchronization.",
    ),
    "arr_identity_mismatch": (
        "Arr returned an unexpected media identity.",
        "Compare stable item identifiers in Radarr or Sonarr before reconciling.",
    ),
    "media_type_missing": (
        "The recorded Jellyfin media type is missing.",
        "Verify whether the item is a movie or series before attempting recovery.",
    ),
    "jellyfin_identity_missing": (
        "The recorded Jellyfin item identity is missing.",
        "Investigate the incomplete intent; do not guess an item from its name.",
    ),
    "arr_fetcher_missing": (
        "Arr inspection is not configured.",
        "Configure read-only service inspection before attempting reconciliation.",
    ),
    "reconciliation_not_authorized": (
        "Read-only checks cannot authorize recovery.",
        "Review the recorded intent and actual external state manually. Automatic clearance remains disabled.",
    ),
}

DEFAULT = (
    "Recovery remains blocked because required verification is incomplete.",
    "Review the operation, Jellyfin protection, and Arr state manually. Do not clear or replay the operation.",
)

PHASES = {
    "intent_recorded": "The operation was recorded, but external completion is not confirmed.",
    "applied_pending_reconciliation": "External success was reported, but independent reconciliation is still required.",
}


def explain_recovery_status(report: dict[str, Any]) -> dict[str, str]:
    """Return fixed, non-authorizing guidance without reflecting input text."""
    if report.get("status") == "no_pending_operation":
        return {
            "summary": "No pending SQLite recovery operation is recorded.",
            "next_step": "No recovery action is indicated by this experimental snapshot.",
        }
    if report.get("status") != "blocked":
        return {
            "summary": "Recovery status is unavailable.",
            "next_step": "Leave media and tracking state unchanged until status can be verified.",
        }
    summary, next_step = GUIDANCE.get(report.get("blocker"), DEFAULT)
    phase = PHASES.get(report.get("operation_phase"))
    result = {"summary": summary, "next_step": next_step}
    if phase:
        result["phase_explanation"] = phase
    return result
