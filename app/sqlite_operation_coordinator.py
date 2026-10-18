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

INTENTS_KEY = "sqlite_pending_operations"
ALLOWED_OPERATIONS = frozenset({"move", "arr_sync"})


class SQLiteOperationCoordinator:
    def __init__(self, session: RevisionedAuditSession):
        self.session = session

    def begin(self, operation_id: str, kind: str, details: dict[str, Any]) -> None:
        """Durably record intent before any external operation is attempted."""
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

    def mark_applied(self, operation_id: str) -> None:
        """Record external success after a caller independently verifies it."""
        pending = self.session.state.get(INTENTS_KEY)
        if not isinstance(pending, dict) or pending.get("id") != operation_id:
            raise RuntimeError("Missing or mismatched SQLite operation intent")
        if pending.get("phase") != "intent_recorded":
            raise RuntimeError("Operation is not awaiting confirmation")
        pending["phase"] = "applied_pending_reconciliation"
        self.session.checkpoint()

    def reconcile(self, operation_id: str, verified_state: dict[str, Any]) -> None:
        """Complete only after the caller has independently verified reality.

        This method does not verify filesystem or Arr state itself. A future
        integration must supply a trusted verifier before calling it.
        """
        pending = self.session.state.get(INTENTS_KEY)
        if not isinstance(pending, dict) or pending.get("id") != operation_id:
            raise RuntimeError("Missing or mismatched SQLite operation intent")
        if pending.get("phase") != "applied_pending_reconciliation":
            raise RuntimeError("Operation has not been confirmed")
        if not isinstance(verified_state, dict):
            raise RuntimeError("Verified state must be a dictionary")
        replacement = deepcopy(verified_state)
        if replacement.get(INTENTS_KEY) != pending:
            raise RuntimeError("Verified state must retain pending intent")
        replacement.pop(INTENTS_KEY)
        self.session.state = replacement
        self.session.checkpoint()
