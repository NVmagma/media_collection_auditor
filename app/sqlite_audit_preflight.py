"""Read-only audit-state parity gate for isolated SQLite rollout checks.

This is not wired into the production auditor. It requires a completed
migration and exact state parity before any future backend activation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.sqlite_integrity import verify_migration_integrity
from app.state_store import GuardedSQLiteStateStore


def prepare_sqlite_audit_state(
    source_json: str | Path,
    backup_json: str | Path,
    database: str | Path,
) -> tuple[GuardedSQLiteStateStore, dict[str, Any], int]:
    """Return a guarded session baseline only after verifying all artifacts.

    No writes or media operations occur here. A missing, stale, or altered
    JSON backup or SQLite snapshot always blocks the proposed activation.
    """
    verify_migration_integrity(source_json, backup_json, database)
    store = GuardedSQLiteStateStore(database)
    state, revision = store.load_with_revision()
    if revision != 0:
        # Migration integrity is a one-time activation gate. After SQLite
        # starts receiving writes, JSON parity is no longer a valid invariant.
        raise RuntimeError("SQLite state already modified; initial parity gate refused")
    verify_migration_integrity(source_json, backup_json, database)
    return store, state, revision
