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
