"""Durable ordering rehearsal only; no exports, services, media or permits.

Records are fixture observations, NEVER proof of external writer exclusion.
There is deliberately no automatic resume, replay, release or production caller.
"""
from contextlib import closing, contextmanager
import os
import re
import secrets
from pathlib import Path
import sqlite3
import stat
import sys
from uuid import UUID

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
# Fresh on interpreter startup; never loaded from retained state or supplied by
# a caller. PID also changes across fork, where Python module memory is copied.
_CONTROLLER_SESSION = secrets.token_hex(32)


def _root(path):
    root = Path(path)
    if not root.is_absolute() or root.resolve() != root:
        raise ValueError("Absolute unaliased disposable root required")
    return root


def _linux_boot_id():
    # Linux-only capability: never substitute wall time, PID, hostname or a
    # caller-supplied value when the kernel boot identity is unavailable.
    if sys.platform != "linux":
        raise RuntimeError("Linux boot identity unavailable")
    try:
        with open("/proc/sys/kernel/random/boot_id", "rb") as source:
            raw = source.read(38)
        value = raw.decode("ascii")
        if len(value) != 37 or not value.endswith("\n"):
            raise ValueError("Invalid boot identity length")
        value = value[:-1]
        parsed = UUID(value)
        if str(parsed) != value or parsed.int == 0:
            raise ValueError("Invalid boot identity")
    except (OSError, ValueError, UnicodeError) as exc:
        raise RuntimeError("Linux boot identity unavailable") from exc
    return value


class MaintenanceControllerSessionChanged(RuntimeError):
    """A new controller process cannot inherit a retained Linux fixture session."""


class MaintenanceNetworkScopeChanged(RuntimeError):
    """A retained fixture belongs to a different Linux network namespace."""


def _linux_network_namespace():
    if sys.platform != "linux":
        raise RuntimeError("Linux network namespace unavailable")
    try:
        value = os.readlink("/proc/self/ns/net")
    except OSError as exc:
        raise RuntimeError("Linux network namespace unavailable") from exc
    if not re.fullmatch(r"net:\[[1-9][0-9]{0,19}\]", value):
        raise RuntimeError("Linux network namespace unavailable")
    return value


def create_disposable_journal(root, *, bind_linux_boot=False):
    """Create a NEW fixture; never accept an existing state/control directory.

    Linux NFS fixtures require boot and network binding. The portable path-only mode is
    retained for synthetic ordering tests, not external writer coordination.
    """
    if type(bind_linux_boot) is not bool:
        raise ValueError("Boolean boot binding selection required")
    boot_id = _linux_boot_id() if bind_linux_boot else None
    network_namespace = _linux_network_namespace() if bind_linux_boot else None
    root = _root(root)
    root.mkdir(mode=0o700)  # Exclusive creation; preserve partial labs on error.
    with (root / ".disposable_maintenance").open("xb") as output:
        output.write(MARKER)
        output.flush()
        os.fsync(output.fileno())
    with closing(sqlite3.connect(root / "maintenance.db")) as db, db:
        db.execute("PRAGMA synchronous=FULL")
        db.execute("CREATE TABLE fixture_binding (path TEXT NOT NULL, root_device INTEGER NOT NULL, "
                   "root_inode INTEGER NOT NULL, db_device INTEGER NOT NULL, db_inode INTEGER NOT NULL, "
                   "linux_boot_id TEXT, linux_network_namespace TEXT, "
                   "controller_pid INTEGER, controller_session TEXT)")
        db.execute("INSERT INTO fixture_binding VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (*_identity(root), boot_id, network_namespace,
                    os.getpid() if bind_linux_boot else None,
                    _CONTROLLER_SESSION if bind_linux_boot else None))
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
    def identity(value):
        if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
            raise RuntimeError("Disposable fixture marker required")
        return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    expected = identity(info)
    try:
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise RuntimeError("Disposable fixture root changed or unavailable") from exc
    marker_fd = None
    try:
        marker_fd = os.open(".disposable_maintenance", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                            dir_fd=root_fd)
        if identity(os.fstat(marker_fd)) != expected:
            raise RuntimeError("Disposable fixture marker changed")
        content = os.pread(marker_fd, len(MARKER) + 1, 0)
        if (content != MARKER or identity(os.fstat(marker_fd)) != expected
                or identity(os.stat(".disposable_maintenance", dir_fd=root_fd, follow_symlinks=False)) != expected):
            raise RuntimeError("Disposable fixture marker changed")
        held_root = os.fstat(root_fd)
        current_root = root.lstat()
        if (held_root.st_dev, held_root.st_ino) != (current_root.st_dev, current_root.st_ino):
            raise RuntimeError("Disposable fixture root changed")
    except OSError as exc:
        raise RuntimeError("Disposable fixture marker changed or unavailable") from exc
    finally:
        if marker_fd is not None:
            os.close(marker_fd)
        os.close(root_fd)


def _identity(root):
    _root(root)
    directory = root.lstat()
    database = (root / "maintenance.db").lstat()
    if (not stat.S_ISDIR(directory.st_mode) or not stat.S_ISREG(database.st_mode)
            or database.st_nlink != 1):
        raise RuntimeError("Unsafe disposable journal identity")
    return (str(root), directory.st_dev, directory.st_ino, database.st_dev, database.st_ino)


def _verify_binding(db, root, *, require_linux_boot=False, require_controller_session=False):
    try:
        rows = db.execute("SELECT path, root_device, root_inode, db_device, db_inode "
                          "FROM fixture_binding").fetchall()
    except sqlite3.Error as exc:
        raise RuntimeError("Disposable journal binding unavailable") from exc
    if rows != [_identity(root)]:
        raise RuntimeError("Disposable journal binding changed")
    try:
        boot_rows = db.execute("SELECT linux_boot_id, linux_network_namespace FROM fixture_binding").fetchall()
    except sqlite3.Error as exc:
        # Old fixture formats are retained for offline review, never upgraded
        # or silently treated as unbound during recovery.
        raise RuntimeError("Disposable journal boot binding unavailable") from exc
    if boot_rows == [(None, None)]:
        if require_linux_boot:
            raise RuntimeError("Linux boot-bound fixture required")
        return  # Portable path-only fixture; never used by the Linux NFS lab.
    if (len(boot_rows) != 1 or not isinstance(boot_rows[0][0], str)
            or not isinstance(boot_rows[0][1], str)):
        raise RuntimeError("Disposable journal boot binding invalid")
    if boot_rows[0][0] != _linux_boot_id():
        raise RuntimeError("Disposable journal boot binding changed")
    if boot_rows[0][1] != _linux_network_namespace():
        raise MaintenanceNetworkScopeChanged("Disposable journal network namespace changed")
    if require_controller_session:
        try:
            sessions = db.execute("SELECT controller_pid, controller_session FROM fixture_binding").fetchall()
        except sqlite3.Error as exc:
            raise RuntimeError("Disposable controller session binding unavailable") from exc
        if (len(sessions) != 1 or type(sessions[0][0]) is not int or sessions[0][0] <= 0
                or not isinstance(sessions[0][1], str) or len(sessions[0][1]) != 64):
            raise RuntimeError("Disposable controller session binding invalid")
        if sessions != [(os.getpid(), _CONTROLLER_SESSION)]:
            raise MaintenanceControllerSessionChanged("Disposable controller session changed")


@contextmanager
def _database(root, *, with_verifier=False):
    root = _root(root)
    _fixture(root)
    with _exclusive_lock(root / "controller.lock", "Disposable controller already held") as verify_lock:
        path = root / "maintenance.db"
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RuntimeError("Unsafe disposable journal")
        db = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True)
        try:
            def verify():
                verify_lock()
                _fixture(root)
                _verify_binding(db, root, require_controller_session=True)
            verify()
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


def inspect_disposable_journal(root, *, require_linux_boot=False):
    """Inspect through a read-only connection; missing journals are not created."""
    if type(require_linux_boot) is not bool:
        raise ValueError("Boolean boot binding requirement required")
    root = _root(root)
    _fixture(root)
    path = root / "maintenance.db"
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise RuntimeError("Unsafe disposable journal")
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("BEGIN")
        _verify_binding(db, root, require_linux_boot=require_linux_boot)
        report = _report(_history(db))
        _verify_binding(db, root, require_linux_boot=require_linux_boot)
        return report


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
