"""Fail-closed planning of state checkpoints around external media operations.

An intent record is persisted before a caller is permitted to perform an
external action. The action itself is never performed by this module. A crash
leaves the intent pending for explicit reconciliation, never automatic replay.
This remains experimental and is not wired into production.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_recovery_pre_move_evidence import (
    build_pre_move_evidence, validate_pre_move_evidence,
)

INTENTS_KEY = "sqlite_pending_operations"
ALLOWED_OPERATIONS = frozenset({"move", "arr_sync", "copy_stage", "arr_import"})


class SQLiteOperationCoordinator:
    def __init__(self, session: RevisionedAuditSession):
        self.session = session

    def begin(self, operation_id: str, kind: str, details: dict[str, Any]) -> None:
        """Durably record intent before any external operation is attempted."""
        self.session.read_verified_snapshot()
        if not isinstance(operation_id, str) or not operation_id:
            raise RuntimeError("Operation ID is required")
        if kind not in ALLOWED_OPERATIONS:
            raise RuntimeError("Unsupported SQLite operation kind")
        if not isinstance(details, dict) or not details:
            raise RuntimeError("Operation details are required")
        if INTENTS_KEY in self.session.state:
            raise RuntimeError("Unresolved SQLite operation; reconciliation required")
        self.session.state[INTENTS_KEY] = {
            "id": operation_id, "kind": kind, "details": deepcopy(details),
            "phase": "intent_recorded",
        }
        self.session.checkpoint()

    def begin_move_with_evidence(
        self, operation_id: str, details: dict[str, Any],
    ) -> None:
        """Checkpoint a candidate pre-move fingerprint with an experimental intent.

        This is not an executor. Callers must not perform external actions
        until begin() successfully checkpoints. Evidence is not trusted proof
        of a completed move, even after restart.
        """
        if not isinstance(details, dict) or not details:
            raise RuntimeError("Operation details are required")
        if "pre_move_evidence" in details:
            raise RuntimeError("Caller-supplied pre-move evidence is not accepted")
        source = details.get("source")
        destination = details.get("destination")
        if (not isinstance(source, str) or not isinstance(destination, str)
                or source == destination):
            raise RuntimeError("Move paths must be distinct")
        # Capture before the durable intent checkpoint; failures never grant
        # permission to perform an external operation.
        evidence = build_pre_move_evidence(source)
        if validate_pre_move_evidence(evidence)["evidence_verification"] != "schema_valid_untrusted":
            raise RuntimeError("Pre-move evidence invalid")
        self.begin(operation_id, "move", {**details, "pre_move_evidence": evidence})

    def mark_applied(self, operation_id: str) -> None:
        """Record external success after a caller independently verifies it."""
        self.session.read_verified_snapshot()
        pending = self.session.state.get(INTENTS_KEY)
        if not isinstance(pending, dict) or pending.get("id") != operation_id:
            raise RuntimeError("Missing or mismatched SQLite operation intent")
        if pending.get("phase") != "intent_recorded":
            raise RuntimeError("Operation is not awaiting confirmation")
        pending["phase"] = "applied_pending_reconciliation"
        self.session.checkpoint()

    def reconcile(self, operation_id: str, verified_state: dict[str, Any]) -> None:
        """Refuse clearance until trusted independent verification is implemented.

        The earlier prototype accepted caller-provided dictionaries as proof.
        That is not sufficient to safely clear a crashed filesystem/Arr action.
        """
        self.session.read_verified_snapshot()
        pending = self.session.state.get(INTENTS_KEY)
        if not isinstance(pending, dict) or pending.get("id") != operation_id:
            raise RuntimeError("Missing or mismatched SQLite operation intent")
        if pending.get("phase") != "applied_pending_reconciliation":
            raise RuntimeError("Operation has not been confirmed")
        raise RuntimeError(
            "SQLite recovery clearance blocked pending trusted verification"
        )
