"""Durable ordering rehearsal only; no exports, services, media or permits.

Records are fixture observations, NEVER proof of external writer exclusion.
There is deliberately no automatic resume, replay, release or production caller.
"""
from contextlib import closing, contextmanager
import os
from pathlib import Path
import sqlite3
import stat

from app.sqlite_lock import _exclusive_lock


NEXT = {
    "prepared": "fence_requested",
    "fence_requested": "fixture_fenced",
    "fixture_fenced": "work_pending",
    "work_pending": "outcomes_verified",
    "outcomes_verified": "release_requested",
    "release_requested": "released",
}
MARKER = b"DISPOSABLE MAINTENANCE JOURNAL ONLY\n"


def _root(path):
    root = Path(path)
    if not root.is_absolute() or root.resolve() != root:
        raise ValueError("Absolute unaliased disposable root required")
    return root


def create_disposable_journal(root):
    """Create a NEW fixture; never accept an existing state/control directory."""
    root = _root(root)
    root.mkdir(mode=0o700)  # Exclusive creation; preserve partial labs on error.
    with (root / ".disposable_maintenance").open("xb") as output:
        output.write(MARKER)
        output.flush()
        os.fsync(output.fileno())
    with closing(sqlite3.connect(root / "maintenance.db")) as db, db:
        db.execute("PRAGMA synchronous=FULL")
        db.execute("CREATE TABLE events (revision INTEGER PRIMARY KEY, phase TEXT NOT NULL)")
        db.execute("INSERT INTO events VALUES (0, 'prepared')")
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    parent = os.open(root.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    return inspect_disposable_journal(root)


def _fixture(root):
    marker = root / ".disposable_maintenance"
    info = marker.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or marker.read_bytes() != MARKER):
        raise RuntimeError("Disposable fixture marker required")


@contextmanager
def _database(root, *, with_verifier=False):
    root = _root(root)
    _fixture(root)
    with _exclusive_lock(root / "controller.lock", "Disposable controller already held") as verify:
        path = root / "maintenance.db"
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RuntimeError("Unsafe disposable journal")
        db = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True)
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            verify()
            yield (db, verify) if with_verifier else db
            verify()
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()


def _append(db, *, expected_revision, phase):
    rows = _history(db)
    revision, current = rows[-1]
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValueError("Nonnegative integer revision required")
    if revision != expected_revision:
        raise RuntimeError("Stale maintenance revision")
    if not isinstance(phase, str) or NEXT.get(current) != phase:
        raise RuntimeError("Invalid maintenance transition")
    db.execute("INSERT INTO events VALUES (?, ?)", (revision + 1, phase))
    return _report(_history(db))


def _history(db):
    rows = db.execute("SELECT revision, phase FROM events ORDER BY revision").fetchall()
    if not rows or rows[0] != (0, "prepared"):
        raise RuntimeError("Invalid maintenance history")
    for previous, current in zip(rows, rows[1:]):
        if current != (previous[0] + 1, NEXT.get(previous[1])):
            raise RuntimeError("Invalid maintenance history")
    return rows


def _report(rows):
    revision, phase = rows[-1]
    return {"revision": revision, "phase": phase,
            "status": "fixture_complete" if phase == "released" else "review_required",
            "automatic_action": "none", "external_writer_exclusion_verified": False,
            "production_authorized": False, "production_activation": "disabled",
            "fixture_only": True}


def inspect_disposable_journal(root):
    """Inspect through a read-only connection; missing journals are not created."""
    root = _root(root)
    _fixture(root)
    path = root / "maintenance.db"
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise RuntimeError("Unsafe disposable journal")
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        return _report(_history(db))


def advance_disposable_journal(root, *, expected_revision, phase):
    """Record one ordered fixture checkpoint using compare-and-swap.

    Caller must explicitly choose every step, including release. This function
    performs NO corresponding external action and grants no execution rights.
    A crash leaves the last committed checkpoint for operator review.
    """
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValueError("Nonnegative integer revision required")
    with _database(root) as db:
        report = _append(db, expected_revision=expected_revision, phase=phase)
    return report
