"""Combined read-only SQLite recovery diagnostics.

Neither matching Arr/filesystem evidence nor Jellyfin observations authorize
clearing an interrupted operation. No service calls or writes occur here.
"""

from __future__ import annotations

from typing import Any

from app.sqlite_jellyfin_recovery import inspect_jellyfin_protection
from app.sqlite_recovery_evidence import evaluate_recovery_evidence


def inspect_combined_recovery(
    state: dict[str, Any],
    *,
    jellyfin_evidence: dict[str, Any] | None,
    arr_record: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Require complete protection data before reporting operation evidence."""
    protection = inspect_jellyfin_protection(jellyfin_evidence)
    report = evaluate_recovery_evidence(state, arr_record=arr_record)
    return {
        **report,
        "jellyfin_protection": protection,
        "authorization": "blocked_pending_independent_verification",
    }
