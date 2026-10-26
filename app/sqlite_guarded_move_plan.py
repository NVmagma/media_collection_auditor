"""Non-executable move plan from an existing SQLite collection preview.

This module cannot authorize a move: candidate actions only express what
production lifecycle decisions propose, not whether filesystem operations
or Jellyfin protection checks have been independently verified.
"""

from __future__ import annotations

ACTION_DESTINATIONS = {
    ("Waiting", "hold"): "Holding",
    ("Waiting", "keep"): "Keep",
    ("Holding", "to_removal"): "Removal",
    ("Holding", "rescue"): "Keep",
}
REQUIRED_CHECKS = (
    "fresh_jellyfin_protection",
    "unique_safe_filesystem_location",
    "same_filesystem_atomic_noreplace",
    "durable_intent_before_move",
    "live_identity_witness",
    "revision_checked_atomic_reconciliation",
    "arr_sync_separate_durable_outcome",
)


def plan_guarded_moves(preview):
    """Produce ordered advisory candidates, never executable permissions."""
    if not isinstance(preview, dict) or preview.get("read_only") is not True:
        raise ValueError("Verified read-only preview required")
    if (preview.get("authorization") != "not_authorized"
            or preview.get("production_activation") != "disabled"
            or type(preview.get("revision")) is not int
            or preview["revision"] < 0
            or not isinstance(preview.get("decisions"), list)):
        raise ValueError("Invalid preview contract")
    if preview.get("tracked_titles") != len(preview["decisions"]):
        raise ValueError("Preview title count mismatch")
    rows = []
    seen = set()
    for entry in preview["decisions"]:
        if not isinstance(entry, dict):
            raise ValueError("Invalid preview row")
        key = entry.get("media_key")
        stages = entry.get("tracked_stages")
        if not isinstance(key, str) or not key or key in seen:
            raise ValueError("Invalid or duplicate media key")
        seen.add(key)
        if not isinstance(stages, list) or len(stages) != 1:
            source = None
        else:
            source = stages[0]
        if source not in ("Waiting", "Holding", "Removal", "Keep"):
            source = None
        candidate = entry.get("candidate_action")
        target = ACTION_DESTINATIONS.get((source, candidate))
        blockers = entry.get("blockers")
        if not isinstance(blockers, list) or any(not isinstance(b, str) for b in blockers):
            raise ValueError("Invalid decision blockers")
        if (entry.get("authorization") != "not_authorized"
                or entry.get("read_only") is not True):
            raise ValueError("Decision row is not advisory")
        if entry.get("status") != "advisory" or blockers or source is None:
            target = None
        rows.append({
            "media_key": key,
            "source_stage": source,
            "candidate_action": candidate,
            "destination_stage": target,
            "status": "candidate_requires_verification" if target else "not_planned",
            "blockers": list(blockers) if blockers else (
                [] if target else ["no_authorized_move_candidate"]),
            "required_checks": list(REQUIRED_CHECKS) if target else [],
            "authorization": "not_authorized",
        })
    return {
        "status": "planning_only",
        "authorization": "not_authorized",
        "production_activation": "disabled",
        "source_revision": preview["revision"],
        "candidate_moves": sum(row["destination_stage"] is not None for row in rows),
        "rows": rows,
        "read_only": True,
    }
