"""Storage boundary for future state backends; production remains JSON-only.

This interface provides a small,
testable contract before changing the auditor's persistence behavior.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class StateStore(Protocol):
    """Load and persist complete lifecycle snapshots without losing history."""

    def load(self) -> dict[str, Any]:
        ...

    def save(self, state: dict[str, Any]) -> None:
        ...


class JsonStateStore:
    """Adapter around the existing, safety-checked production JSON routines.

    No new JSON parsing, locking, or write behavior is introduced here.
    """

    def __init__(self, state_path: str | Path):
        self.state_path = Path(state_path)

    def load(self) -> dict[str, Any]:
        from app import collection_auditor

        original = collection_auditor.STATE_FILE
        if Path(original).resolve() != self.state_path.resolve():
            raise RuntimeError("JSON store path differs from configured auditor state")
        return collection_auditor.load_state()

    def save(self, state: dict[str, Any]) -> None:
        from app import collection_auditor

        original = collection_auditor.STATE_FILE
        if Path(original).resolve() != self.state_path.resolve():
            raise RuntimeError("JSON store path differs from configured auditor state")
        collection_auditor.save_state(state)
