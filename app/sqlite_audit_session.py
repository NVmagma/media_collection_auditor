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

    @property
    def revision(self) -> int:
        return self._revision

    def checkpoint(self) -> None:
        """Persist a snapshot, refusing to overwrite a concurrent audit."""
        # Never hand a mutable reference to the backend while it is writing.
        snapshot = deepcopy(self.state)
        self._store.save_if_revision(snapshot, self._revision)
        # Re-read to get the revision and ensure the committed content matches.
        confirmed, revision = self._store.load_with_revision()
        if confirmed != snapshot or revision != self._revision + 1:
            raise RuntimeError("SQLite audit checkpoint could not be verified")
        self._revision = revision
