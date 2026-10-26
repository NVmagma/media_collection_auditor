"""Conservative Jellyfin evidence gate for SQLite recovery diagnostics.

This module never calls Jellyfin or authorizes recovery. It only validates a
fresh caller-supplied protection observation; absence is always a hard block.
"""

from __future__ import annotations

from typing import Any


def inspect_jellyfin_protection(evidence: dict[str, Any] | None) -> str:
    """Require explicit complete, unprotected Jellyfin evidence.

    A caller must independently fetch and authenticate the evidence. This
    shape is not a substitute for that future integration.
    """
    if not isinstance(evidence, dict):
        raise RuntimeError("Jellyfin protection information unavailable")
    if evidence.get("available") is not True:
        raise RuntimeError("Jellyfin protection information unavailable")
    if evidence.get("complete") is not True:
        raise RuntimeError("Jellyfin protection information incomplete")
    for key in ("keep", "keep_forever", "keep_all_seasons", "favorite"):
        if type(evidence.get(key)) is not bool:
            raise RuntimeError("Jellyfin protection information invalid")
    if any(evidence[key] for key in ("keep", "keep_forever", "keep_all_seasons", "favorite")):
        return "protected_manual_review_required"
    return "unprotected_but_recovery_still_blocked"
