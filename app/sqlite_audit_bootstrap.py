"""Isolated SQLite audit bootstrap; never dispatches media operations.

This explicit function is for disposable test databases only. Production
run_once() still uses JSON and never imports this module.
"""

from __future__ import annotations

from pathlib import Path

from app.sqlite_audit_preflight import prepare_sqlite_audit_state
from app.sqlite_audit_session import RevisionedAuditSession


def open_isolated_sqlite_audit(
    source_json: str | Path,
    backup_json: str | Path,
    database: str | Path,
) -> RevisionedAuditSession:
    """Open a revision-guarded session only after migration parity passes.

    Re-check the session's initial revision and content to catch a competing
    writer between preflight and session creation. No audit actions run.
    """
    store, baseline, revision = prepare_sqlite_audit_state(
        source_json, backup_json, database
    )
    session = RevisionedAuditSession(store)
    if session.revision != revision or session.state != baseline:
        raise RuntimeError("SQLite state changed during isolated audit bootstrap")
    return session
