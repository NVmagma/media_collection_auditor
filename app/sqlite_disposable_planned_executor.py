"""Strict plan-bound disposable entry point; never call from production.

The legacy disposable move runner remains available for isolated regression
tests. This integration entry point refuses calls without a full advisory plan.
Neither entry point verifies Jellyfin freshness or authorizes production.
"""

from __future__ import annotations

from app.sqlite_disposable_lifecycle_flow import execute_disposable_lifecycle_move
from app.sqlite_guarded_move_plan import REQUIRED_CHECKS


def rehearse_planned_disposable_move(*, root, database, operation_id, media_key,
                                    planned_move, source_stage="transient",
                                    destination_stage="holding", observed_at=None,
                                    fault_at=None):
    """Require a bound candidate before delegating to the disposable runner."""
    revision = validate_disposable_move_candidate(
        planned_move=planned_move, media_key=media_key,
        source_stage=source_stage, destination_stage=destination_stage)
    return execute_disposable_lifecycle_move(
        root=root, database=database, operation_id=operation_id,
        media_key=media_key, source_stage=source_stage,
        destination_stage=destination_stage, observed_at=observed_at,
        fault_at=fault_at, expected_revision=revision,
        planned_move=planned_move)


def validate_disposable_move_candidate(*, planned_move, media_key,
                                       source_stage, destination_stage):
    """Validate a non-authorizing candidate shape, without state or media IO."""
    if not isinstance(planned_move, dict):
        raise ValueError("A complete disposable advisory plan is required")
    plan = planned_move.get("plan")
    if not isinstance(plan, dict):
        raise ValueError("A complete disposable advisory plan is required")
    revision = plan.get("source_revision")
    if type(revision) is not int or revision < 0:
        raise ValueError("A valid plan revision is required")
    if (plan.get("authorization") != "not_authorized"
            or plan.get("production_activation") != "disabled"
            or plan.get("read_only") is not True
            or plan.get("status") != "planning_only"):
        raise ValueError("Only non-authorizing advisory plans are supported")
    mapping = {"transient": "Waiting", "holding": "Holding",
               "removal": "Removal", "keep": "Keep"}
    rows = plan.get("rows")
    if not isinstance(rows, list):
        raise ValueError("Invalid plan rows")
    matches = [row for row in rows if isinstance(row, dict)
               and row.get("media_key") == media_key]
    if (len(matches) != 1
            or matches[0].get("source_stage") != mapping.get(source_stage)
            or matches[0].get("destination_stage") != mapping.get(destination_stage)
            or matches[0].get("status") != "candidate_requires_verification"
            or matches[0].get("required_checks") != list(REQUIRED_CHECKS)
            or matches[0].get("authorization") != "not_authorized"):
        raise RuntimeError("No matching disposable advisory move candidate")
    return revision
