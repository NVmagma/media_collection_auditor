"""Isolated SQLite state adapter for disposable, read-only integration checks.

Not imported by production run_once(). No media operations or state writes.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from app.sqlite_audit_bootstrap import open_isolated_sqlite_audit
from app.sqlite_operation_coordinator import INTENTS_KEY


def inspect_isolated_audit_state(
    source_json: str | Path,
    backup_json: str | Path,
    database: str | Path,
) -> dict[str, Any]:
    """Return detached verified tracking state, never permission to act."""
    session = open_isolated_sqlite_audit(source_json, backup_json, database)
    state, revision = session.read_verified_snapshot()
    if INTENTS_KEY in state:
        raise RuntimeError("Unresolved SQLite operation; isolated inspection blocked")
    return {
        "revision": revision,
        "state": deepcopy(state),
        "authorization": "not_authorized",
        "production_activation": "disabled",
        "storage_authority": "json",
    }
