"""Keep JSON storage behind a small interface that is easy to test.

The application uses JSON only. This interface does not change how the existing
loader, locks, or saves work.
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
    """Use the existing JSON loader and save functions.

    Keep their parsing, locking, and write behavior unchanged.
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
