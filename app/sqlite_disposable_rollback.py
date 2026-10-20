"""Fresh JSON rollback candidates for marked labs; never restore or activate.

Candidates contain tracking data and must remain private. Failed/uncertain
outputs are retained for inspection and never overwritten or automatically used.
"""
import json
import os
from pathlib import Path
import stat

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_isolated_lifecycle_runner import isolated_runner_lock
from app.sqlite_json import parse_unique_json
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_state import validate_snapshot
from app.sqlite_title_identity import validate_title_folder
from app.state_store import GuardedSQLiteStateStore

FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _candidate_name(name):
    name = validate_title_folder(name)
    if not name.startswith("rollback-candidate-") or not name.endswith(".json"):
        raise ValueError("Private rollback candidate filename required")
    return name


def _snapshot(root):
    session = RevisionedAuditSession(GuardedSQLiteStateStore(root / "state.db"))
    state, revision = session.read_verified_snapshot()
    validate_snapshot(state)
    if INTENTS_KEY in state:
        raise RuntimeError("Unresolved operation blocks JSON rollback candidate")
    return session, state, revision


def _read_candidate(parent, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise RuntimeError("Regular private candidate required")
        chunks = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(fd)
        current = os.stat(name, dir_fd=parent, follow_symlinks=False)
        identity = lambda value: (value.st_dev, value.st_ino, value.st_size,
                                  value.st_mtime_ns, value.st_ctime_ns, value.st_nlink)
        if identity(before) != identity(after) or identity(after) != identity(current):
            raise RuntimeError("Rollback candidate changed during inspection")
        parsed = parse_unique_json(b"".join(chunks))
        validate_snapshot(parsed)
        if INTENTS_KEY in parsed:
            raise RuntimeError("Candidate contains unresolved operation")
        return parsed
    finally:
        os.close(fd)


def _report(revision, matches):
    return {"status": "matching_candidate_advisory_only" if matches else "blocked",
            "reason": "current_snapshot_matches" if matches else "candidate_differs_from_current_snapshot",
            "revision": revision, "authorization": "not_authorized",
            "production_activation": "disabled", "storage_authority": "json",
            "restore_performed": False, "media_actions_performed": False}


def export_disposable_rollback_candidate(*, root, candidate_name):
    """Export current advanced state exclusively; success never authorizes restore."""
    root = Path(root)
    name = _candidate_name(candidate_name)
    with isolated_runner_lock(root) as verify_binding:
        session, state, revision = _snapshot(root)
        payload = json.dumps(state, ensure_ascii=True, allow_nan=False,
                             sort_keys=True, indent=2).encode("ascii") + b"\n"
        parent = os.open(root, FLAGS)
        try:
            verify_binding()
            session.read_verified_snapshot()
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=parent)
            try:
                remaining = memoryview(payload)
                while remaining:
                    written = os.write(fd, remaining)
                    if written <= 0:
                        raise OSError("Rollback candidate write stopped")
                    remaining = remaining[written:]
                os.fsync(fd)
            finally:
                os.close(fd)
            os.fsync(parent)
            if _read_candidate(parent, name) != state:
                raise RuntimeError("Rollback candidate parity mismatch")
            verify_binding()
            session.read_verified_snapshot()
            return _report(revision, True)
        finally:
            os.close(parent)


def inspect_disposable_rollback_candidate(*, root, candidate_name):
    """Reject a stale candidate by comparing against the current SQLite snapshot."""
    root = Path(root)
    name = _candidate_name(candidate_name)
    with isolated_runner_lock(root) as verify_binding:
        session, state, revision = _snapshot(root)
        parent = os.open(root, FLAGS)
        try:
            candidate = _read_candidate(parent, name)
            verify_binding()
            session.read_verified_snapshot()
            return _report(revision, candidate == state)
        finally:
            os.close(parent)
