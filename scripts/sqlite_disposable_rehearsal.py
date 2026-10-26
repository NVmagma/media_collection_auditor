"""Explicit, disposable-only SQLite lab rehearsal. Never production-wired.

CLI fixes /lab; helper functions accept test directories only for pytest.
No cleanup, reconciliation, overwrite, or production media operations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_operation_coordinator import INTENTS_KEY, SQLiteOperationCoordinator
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore
from scripts.sqlite_lab_fixture_guard import (
    FIXTURE_NAMES, inspect_disposable_destination_slot,
    inspect_lab_mount_boundaries, validate_disposable_lab,
    verify_disposable_fixture_digest,
)

PAYLOAD = b"media-collection-auditor-disposable-sqlite-lab-v1\\n"
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()
OPERATION_ID = "disposable-lab-move-v1"


def _paths(lab: Path) -> tuple[Path, Path, Path]:
    return tuple(lab / name for name in FIXTURE_NAMES)


def _sync_directory(lab: Path) -> None:
    fd = os.open(lab, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def prepare(lab: Path) -> dict:
    """Only called after the CLI has validated an empty isolated mount."""
    source, destination, database = _paths(lab)
    if any(path.exists() or path.is_symlink() for path in (source, destination, database)):
        raise RuntimeError("Disposable lab fixture occupied")
    with source.open("xb") as output:
        output.write(PAYLOAD)
        output.flush()
        os.fsync(output.fileno())
    _sync_directory(lab)
    write_offline_snapshot({section: {} for section in SECTIONS}, database)
    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    SQLiteOperationCoordinator(session).begin(
        OPERATION_ID, "move",
        {"source": str(source), "destination": str(destination),
         "fixture_kind": "disposable_regular_file", "sha256": DIGEST},
    )
    return inspect(lab)


def inspect(lab: Path) -> dict:
    """Read-only status, never treating a digest as replay authorization."""
    source, destination, database = _paths(lab)
    state, revision = GuardedSQLiteStateStore(database).load_with_revision()
    pending = state.get(INTENTS_KEY)
    if not isinstance(pending, dict) or pending.get("id") != OPERATION_ID:
        raise RuntimeError("Disposable pending intent unavailable")
    if pending.get("kind") != "move" or pending.get("phase") not in (
        "intent_recorded", "applied_pending_reconciliation"
    ):
        raise RuntimeError("Disposable intent invalid")
    details = pending.get("details")
    if not isinstance(details, dict) or details.get("source") != str(source) or (
        details.get("destination") != str(destination)
        or details.get("sha256") != DIGEST
        or details.get("fixture_kind") != "disposable_regular_file"
    ):
        raise RuntimeError("Disposable intent identity mismatch")
    def observed(path: Path) -> str:
        if not path.exists() and not path.is_symlink():
            return "missing"
        result = verify_disposable_fixture_digest(path, DIGEST, lab)
        return "digest_matches_unverified" if result["reason"] == "local_digest_matches" else "blocked"
    before = (observed(source), observed(destination))
    after_state, after_revision = GuardedSQLiteStateStore(database).load_with_revision()
    if (after_state, after_revision) != (state, revision):
        raise RuntimeError("SQLite changed during inspection")
    if (observed(source), observed(destination)) != before:
        raise RuntimeError("Fixture changed during inspection")
    return {"status": "blocked", "authorization": "not_authorized",
            "revision": revision, "phase": pending["phase"],
            "source": before[0], "destination": before[1],
            "storage_authority": "json"}


def move(lab: Path) -> dict:
    """One deliberate no-overwrite move; never automatically replay."""
    source, destination, database = _paths(lab)
    observation = inspect(lab)
    if (observation["phase"] != "intent_recorded"
            or observation["source"] != "digest_matches_unverified"
            or observation["destination"] != "missing"):
        raise RuntimeError("Unsafe or already-attempted disposable move")
    if inspect_disposable_destination_slot(destination, lab)["reason"] != "slot_unoccupied_unverified":
        raise RuntimeError("Disposable destination occupied")
    # Hard link creation is exclusive and cannot replace an existing object.
    # This requires a single filesystem, as supplied by the /lab bind mount.
    os.link(source, destination, follow_symlinks=False)
    _sync_directory(lab)
    os.unlink(source)
    _sync_directory(lab)
    return inspect(lab)


def applied(lab: Path) -> dict:
    observation = inspect(lab)
    if (observation["phase"] != "intent_recorded"
            or observation["source"] != "missing"
            or observation["destination"] != "digest_matches_unverified"):
        raise RuntimeError("Disposable move cannot be marked applied")
    database = _paths(lab)[2]
    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    SQLiteOperationCoordinator(session).mark_applied(OPERATION_ID)
    return inspect(lab)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "inspect", "move", "applied"))
    parser.add_argument("--execute-disposable-lab", action="store_true")
    args = parser.parse_args()
    if not args.execute_disposable_lab:
        parser.error("Explicit --execute-disposable-lab required")
    lab = Path("/lab")
    if lab.is_symlink() or not lab.is_dir() or not os.path.ismount(lab):
        raise SystemExit("Dedicated /lab mount required")
    mount = inspect_lab_mount_boundaries(Path("/proc/self/mountinfo").read_text())
    if mount["status"] != "observed_unverified":
        raise SystemExit("Lab mount verification blocked: " + mount["reason"])
    if args.phase == "prepare":
        validate_disposable_lab(lab)
        result = prepare(lab)
    else:
        result = {"inspect": inspect, "move": move, "applied": applied}[args.phase](lab)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
