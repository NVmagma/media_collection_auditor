"""Read-only recovery inspection from a persisted SQLite session.

This deliberately does not clear intents, trust caller-provided Jellyfin data
as authorization, or perform media/Arr operations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_combined_recovery import inspect_combined_recovery
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.state_store import GuardedSQLiteStateStore


def inspect_persisted_recovery(
    database: str | Path,
    *,
    jellyfin_evidence: dict[str, Any] | None,
    arr_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Inspect a fresh database snapshot and reject concurrent changes."""
    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    state, revision = session.read_verified_snapshot()
    if INTENTS_KEY not in state:
        raise RuntimeError("No pending SQLite operation to inspect")
    report = inspect_combined_recovery(
        state, jellyfin_evidence=jellyfin_evidence, arr_record=arr_record
    )
    # Do not return an apparently current report if another writer intervened.
    session.read_verified_snapshot()
    return {
        **report,
        "revision": revision,
        "storage_authority": "json",
        "production_activation": "disabled",
        "authorization": "blocked_pending_independent_verification",
    }
