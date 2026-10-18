"""Read-only SQLite activation readiness report; never enables a backend.

This diagnostic cannot authorize migration, reconciliation, or media actions.
JSON remains the production authority.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.sqlite_audit_preflight import prepare_sqlite_audit_state
from app.sqlite_operation_coordinator import INTENTS_KEY


def inspect_sqlite_readiness(
    source_json: str | Path,
    backup_json: str | Path,
    database: str | Path,
) -> dict[str, Any]:
    """Report blockers without changing any state or claiming activation safety."""
    report: dict[str, Any] = {
        "ready_for_isolated_review": False,
        "production_activation": "disabled",
        "storage_authority": "json",
        "blockers": [],
        "revision": None,
    }
    try:
        store, baseline, revision = prepare_sqlite_audit_state(
            source_json, backup_json, database
        )
        persisted, current_revision = store.load_with_revision()
        if revision != current_revision or baseline != persisted:
            report["blockers"].append("state_changed_during_inspection")
        elif INTENTS_KEY in baseline:
            report["blockers"].append("unresolved_operation_requires_reconciliation")
        else:
            report["revision"] = revision
            report["ready_for_isolated_review"] = True
    except Exception:
        # No partial or unverified evidence may be interpreted as approval.
        report["blockers"].append("migration_or_snapshot_verification_failed")
    return report
