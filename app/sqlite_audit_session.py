"""Experimental audit state session; no production backend selection.

A session retains the revision loaded at audit start. Every checkpoint uses
compare-and-swap so stale workers cannot silently replace newer tracking.
This module performs no media moves, deletes, or Jellyfin calls.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.state_store import RevisionedStateStore


class RevisionedAuditSession:
    """One audit's tracked state with explicit guarded persistence."""

    def __init__(self, store: RevisionedStateStore):
        self._store = store
        state, revision = store.load_with_revision()
        self.state: dict[str, Any] = state
        self._revision = revision
        self._checkpoint_failed = False

    @property
    def revision(self) -> int:
        return self._revision

    def read_verified_snapshot(self) -> tuple[dict[str, Any], int]:
        """Return a detached snapshot only if the session is still current."""
        if self._checkpoint_failed:
            raise RuntimeError("SQLite session invalid after failed checkpoint; reopen required")
        persisted, revision = self._store.load_with_revision()
        if revision != self._revision or persisted != self.state:
            raise RuntimeError("SQLite recovery session is stale")
        return deepcopy(persisted), revision

    def checkpoint(self) -> None:
        """Persist once; quarantine this session if outcome is uncertain.

        A write may have committed before an exception was raised. Never retry
        with the same session after any failure: reopen and inspect the store.
        """
        if self._checkpoint_failed:
            raise RuntimeError("SQLite session invalid after failed checkpoint; reopen required")
        try:
            snapshot = deepcopy(self.state)
            self._store.save_if_revision(snapshot, self._revision)
            confirmed, revision = self._store.load_with_revision()
            if confirmed != snapshot or revision != self._revision + 1:
                raise RuntimeError("SQLite audit checkpoint could not be verified")
            self._revision = revision
        except Exception:
            self._checkpoint_failed = True
            raise
