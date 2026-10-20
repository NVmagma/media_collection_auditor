"""Test-only SQLite reconciliation for an in-process witnessed rename.

Never use for crash recovery or production. A witness is a live directory file
descriptor held across the rename, not persisted evidence. After process exit
it cannot be reconstructed, so uncertain operations remain unresolved.
"""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import stat

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_lifecycle_checkpoint_plan import CLOCKS, TRANSITIONS
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.state_store import GuardedSQLiteStateStore

STAGE_NAMES = {"transient": "Waiting", "holding": "Holding",
               "removal": "Removal", "keep": "Keep"}


def reconcile_witnessed_disposable_rename(*, root, database, operation_id,
                                          media_key, source_stage,
                                          destination_stage, observed_at,
                                          witness_fd, require_clock_binding=False):
    """Commit clock and intent clearance in one guarded snapshot transaction.

    Requires a live, independently opened pre-rename directory descriptor.
    Caller must retain it across the rename. Never recover this from disk.
    """
    root = Path(root)
    database = Path(database)
    if (not root.is_absolute() or root.is_symlink() or not root.is_dir()
            or root.resolve() != root or database != root / "state.db"
            or database.is_symlink()):
        raise RuntimeError("Not an isolated disposable database")
    marker = root / ".sqlite_disposable_rehearsal"
    if (marker.is_symlink() or not marker.is_file()
            or marker.read_text() != "DISPOSABLE ONLY\n"):
        raise RuntimeError("Disposable marker missing")
    transition = (STAGE_NAMES.get(source_stage), STAGE_NAMES.get(destination_stage))
    if transition not in TRANSITIONS:
        raise RuntimeError("Unsupported transition")
    if (not isinstance(observed_at, datetime) or observed_at.tzinfo is not None
            or observed_at > datetime.now()):
        raise RuntimeError("Invalid observation time")
    if not isinstance(media_key, str) or not media_key:
        raise RuntimeError("Invalid media key")
    try:
        witnessed = os.fstat(witness_fd)
    except (OSError, TypeError, ValueError) as exc:
        raise RuntimeError("Live rename witness unavailable") from exc
    if not stat.S_ISDIR(witnessed.st_mode):
        raise RuntimeError("Witness is not a directory")
    source = root / source_stage / "Movie"
    destination = root / destination_stage / "Movie"
    for stage in STAGE_NAMES:
        directory = root / stage
        if directory.is_symlink() or not directory.is_dir():
            raise RuntimeError("Unsafe stage root")
        candidate = directory / "Movie"
        if candidate.is_symlink():
            raise RuntimeError("Unsafe stage title")
        if stage == destination_stage:
            if not candidate.is_dir():
                raise RuntimeError("Destination unavailable")
        elif candidate.exists():
            raise RuntimeError("Ambiguous title location")
    if source.exists() or source.is_symlink():
        raise RuntimeError("Source still exists")
    destination_stat = os.stat(destination, follow_symlinks=False)
    if (destination_stat.st_dev, destination_stat.st_ino) != (
            witnessed.st_dev, witnessed.st_ino):
        raise RuntimeError("Witness does not match destination")

    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    persisted, _ = session.read_verified_snapshot()
    intent = persisted.get(INTENTS_KEY)
    if (not isinstance(intent, dict) or intent.get("id") != operation_id
            or intent.get("kind") != "move"
            or intent.get("phase") != "applied_pending_reconciliation"
            or not isinstance(intent.get("details"), dict)
            or intent["details"].get("media_key") != media_key
            or intent["details"].get("source") != str(source)
            or intent["details"].get("destination") != str(destination)):
        raise RuntimeError("Persisted intent binding unavailable")
    source_clock, destination_clock = CLOCKS[transition[0]], CLOCKS[transition[1]]
    if (media_key not in persisted[source_clock]
            or any(media_key in persisted[section] for section in CLOCKS.values()
                   if section != source_clock)):
        raise RuntimeError("Lifecycle clock conflict")
    if observed_at < datetime.fromisoformat(persisted[source_clock][media_key]):
        raise RuntimeError("Lifecycle observation predates source clock")
    binding = intent["details"].get("lifecycle_clock_binding")
    expected_binding = {
        "source_stage": source_stage, "destination_stage": destination_stage,
        "source_timestamp": persisted[source_clock][media_key],
        "observed_at": observed_at.isoformat(),
    }
    if ((require_clock_binding or "lifecycle_clock_binding" in intent["details"])
            and binding != expected_binding):
        raise RuntimeError("Persisted lifecycle clock binding mismatch")
    session.state[source_clock].pop(media_key)
    session.state[destination_clock][media_key] = observed_at.isoformat()
    session.state.pop(INTENTS_KEY)
    # One CAS commit; on uncertain failure the session is quarantined.
    session.checkpoint()
    return {"status": "disposable_reconciled",
            "production_activation": "disabled", "recovery_authorized": False}
