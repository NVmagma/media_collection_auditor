"""Revision-bound, read-only recovery diagnostics for SQLite sessions.

A diagnostic cannot authorize clearing a pending intent. Re-read the backing
store after inspection so concurrent checkpoint changes invalidate the report.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_combined_recovery import inspect_combined_recovery


def inspect_session_recovery(
    session: RevisionedAuditSession,
    *,
    jellyfin_evidence: dict[str, Any] | None,
    arr_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reject stale sessions and concurrent state changes during inspection."""
    baseline, revision = session._store.load_with_revision()
    if revision != session.revision or baseline != session.state:
        raise RuntimeError("SQLite recovery session is stale")
    report = inspect_combined_recovery(
        deepcopy(baseline),
        jellyfin_evidence=jellyfin_evidence,
        arr_record=arr_record,
    )
    confirmed, confirmed_revision = session._store.load_with_revision()
    if confirmed_revision != revision or confirmed != baseline:
        raise RuntimeError("SQLite recovery state changed during inspection")
    return {**report, "state_revision": revision}
