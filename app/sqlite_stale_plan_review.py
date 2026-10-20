"""Read-only revalidation of an advisory plan against current SQLite state.

Caller-supplied signals are not proof of freshness. This review cannot
authorize moves or replace live Jellyfin protection verification.
"""

from __future__ import annotations

from app.sqlite_collection_decision_preview import preview_collection
from app.sqlite_guarded_move_plan import plan_guarded_moves


def review_plan_again(*, database, original_plan, now, thresholds,
                      signals_by_key, favorites_trigger_keep=True):
    """Compare a plan with a freshly loaded revision and recomputed decisions."""
    if not isinstance(original_plan, dict):
        raise ValueError("Original plan required")
    if (original_plan.get("authorization") != "not_authorized"
            or original_plan.get("production_activation") != "disabled"
            or original_plan.get("read_only") is not True
            or original_plan.get("status") != "planning_only"
            or type(original_plan.get("source_revision")) is not int):
        raise ValueError("Untrusted plan contract")
    current = plan_guarded_moves(preview_collection(
        database=database, now=now, thresholds=thresholds,
        signals_by_key=signals_by_key,
        favorites_trigger_keep=favorites_trigger_keep))
    blockers = []
    if current["source_revision"] != original_plan["source_revision"]:
        blockers.append("sqlite_revision_changed")
    if current["rows"] != original_plan.get("rows"):
        blockers.append("lifecycle_plan_changed")
    if current["candidate_moves"] != original_plan.get("candidate_moves"):
        blockers.append("candidate_count_changed")
    return {
        "status": "blocked" if blockers else "unchanged_advisory_only",
        "blockers": blockers,
        "source_revision": original_plan["source_revision"],
        "current_revision": current["source_revision"],
        "authorization": "not_authorized",
        "production_activation": "disabled",
        "fresh_jellyfin_verification": "not_established",
        "read_only": True,
    }
