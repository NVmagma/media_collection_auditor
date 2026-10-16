"""Pure lifecycle decisions shared by the auditor and dashboard.

This module never reads media paths, calls services, or modifies files.
A decision is only a candidate; filesystem and integration safety checks
remain the responsibility of the auditor.
"""


def decide(stage, age, wait_days, signals=None, favorites_trigger_keep=True):
    """Return (action, explanation). None signals means Jellyfin is unknown."""
    if stage == "Waiting":
        if signals is None:
            return "unknown", "Jellyfin data unavailable; do not assume this title can move."
        if signals.get("protected"):
            return "keep", "Protected by keep-forever tag; all TV seasons preserved."
        if signals.get("keep"):
            return "keep", "Tagged keep in Jellyfin."
        if favorites_trigger_keep and signals.get("favorite"):
            return "keep", "Favorited in Jellyfin (legacy favorite support)."
        if signals.get("disliked"):
            return "hold", "Tagged as disliked in Jellyfin."
        if age is not None and age >= wait_days:
            return "hold", "Waiting period expired without a favorite."
        return "wait", "Still inside the waiting period."
    if stage == "Holding":
        if signals is None:
            return "unknown", "Jellyfin data unavailable; favorite rescue cannot be ruled out."
        if signals.get("protected"):
            return "rescue", "Protected by keep-forever tag; all TV seasons preserved."
        if signals.get("keep"):
            return "rescue", "Tagged keep in Jellyfin."
        if favorites_trigger_keep and signals.get("favorite"):
            return "rescue", "Favorited in Jellyfin (legacy favorite support)."
        if age is not None and age >= wait_days:
            return "to_removal", "Holding period expired without a favorite."
        return "wait", "Still inside the holding period."
    if stage == "Removal":
        if age is not None and age >= wait_days:
            return "delete_candidate", "Removal period expired; deletion safeguards still apply."
        return "wait", "Still inside the removal period."
    return "none", "No lifecycle move proposed for this stage."
