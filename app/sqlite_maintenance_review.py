"""Detached, read-only review of retained disposable maintenance evidence.

This reader never calls transition/controller APIs, rebinds a fixture or grants
execution rights. Scope drift can be reported without accepting it for use.
"""
from contextlib import closing
import os
import sqlite3
import stat

from app import sqlite_disposable_maintenance_journal as journal

MAX_JOURNAL_BYTES = 1024 * 1024


def _file_identity(info):
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise RuntimeError("Unsafe retained fixture database")
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _require_no_sidecars(root):
    # A raw main-file image is not a committed snapshot when recovery/WAL state
    # exists. Never recover, checkpoint, delete or inspect those source files.
    for suffix in ("-journal", "-wal", "-shm"):
        if os.path.lexists(root / ("maintenance.db" + suffix)):
            raise RuntimeError("Retained fixture has unresolved SQLite sidecars")


def _snapshot(root):
    """Read a bounded file image; SQLite never opens the source or sidecars."""
    _require_no_sidecars(root)
    path = root / "maintenance.db"
    expected = _file_identity(path.lstat())
    if expected[2] > MAX_JOURNAL_BYTES:
        raise RuntimeError("Retained fixture exceeds review bound")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if _file_identity(os.fstat(fd)) != expected:
            raise RuntimeError("Retained fixture changed during review")
        content = bytearray()
        while len(content) <= MAX_JOURNAL_BYTES:
            chunk = os.read(fd, min(65536, MAX_JOURNAL_BYTES + 1 - len(content)))
            if not chunk:
                break
            content.extend(chunk)
        if (len(content) != expected[2] or len(content) > MAX_JOURNAL_BYTES
                or _file_identity(os.fstat(fd)) != expected
                or _file_identity(path.lstat()) != expected):
            raise RuntimeError("Retained fixture changed during review")
        return bytes(content), expected
    finally:
        os.close(fd)


def _runtime_scope(db):
    try:
        rows = db.execute("SELECT linux_boot_id, linux_network_namespace "
                          "FROM fixture_binding LIMIT 2").fetchall()
    except sqlite3.Error:
        return {"linux_boot": "unavailable", "network_namespace": "unavailable"}
    if rows == [(None, None)]:
        return {"linux_boot": "unbound_fixture", "network_namespace": "unbound_fixture"}
    if len(rows) != 1 or not all(isinstance(value, str) for value in rows[0]):
        return {"linux_boot": "invalid", "network_namespace": "invalid"}
    result = {}
    for name, value, reader in (
            ("linux_boot", rows[0][0], journal._linux_boot_id),
            ("network_namespace", rows[0][1], journal._linux_network_namespace)):
        try:
            result[name] = "matching" if value == reader() else "changed"
        except (OSError, RuntimeError):
            result[name] = "unavailable"
    return result


def review_disposable_maintenance(root):
    """Report evidence even after scope drift; NEVER return resume clearance.

    Only a marked, canonical disposable fixture is accepted. Queries use a
    detached in-memory image, so even a WAL-mode source cannot cause SQLite to
    create locks, journals or sidecars alongside the retained evidence.
    """
    root = journal._root(root)
    journal._fixture(root)
    identity = journal._identity(root)
    content, file_identity = _snapshot(root)
    report = {"status": "review_required", "read_only": True, "fixture_only": True,
              "source": "detached_fixture_snapshot", "revision": None, "phase": None,
              "scope_comparison": "identifiers_only", "controller_session_verified": False,
              "history_valid": False, "scope": {}, "automatic_action": "none",
              "resume_authorized": False, "clearance_authorized": False,
              "production_authorized": False, "production_activation": "disabled",
              "writer_exclusion_verified": False, "restart_inhibition_verified": False,
              "blockers": ["fixture_review_never_authorizes_execution"]}
    with closing(sqlite3.connect(":memory:")) as db:
        if not hasattr(db, "deserialize"):
            raise RuntimeError("Detached SQLite review unavailable")
        db.deserialize(content)
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("PRAGMA temp_store=MEMORY")
        try:
            revision, phase = journal._history(db)[-1]
            report.update(revision=revision, phase=phase, history_valid=True)
        except (sqlite3.Error, RuntimeError):
            report["blockers"].append("fixture_history_invalid_or_unavailable")
        if db.execute("SELECT 1 FROM sqlite_master WHERE lower(name)=? LIMIT 1",
                      ("maintenance_copy_binding",)).fetchone():
            report["maintenance_copy_attempt_present"] = True
            report["blockers"].append("retained_media_attempt_requires_review")
        if journal._client_writeback_uncertain(db):
            report["client_writeback_uncertain"] = True
            report["blockers"].append("client_writeback_outcome_uncertain")
        try:
            rows = db.execute("SELECT path, root_device, root_inode, db_device, db_inode "
                              "FROM fixture_binding LIMIT 2").fetchall()
            report["scope"]["path_identity"] = "matching" if rows == [identity] else "changed"
        except sqlite3.Error:
            report["scope"]["path_identity"] = "unavailable"
        report["scope"].update(_runtime_scope(db))
    for name, observation in report["scope"].items():
        if observation != "matching":
            report["blockers"].append(name + "_" + observation)
    # A replaced source must not inherit the report from the opened image.
    journal._fixture(root)
    _require_no_sidecars(root)
    if (journal._identity(root) != identity
            or _file_identity((root / "maintenance.db").lstat()) != file_identity):
        raise RuntimeError("Retained fixture changed during review")
    return report
