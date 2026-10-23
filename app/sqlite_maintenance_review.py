"""Detached, read-only review of retained disposable maintenance evidence.

This reader never calls transition/controller APIs, rebinds a fixture or grants
execution rights. Scope drift can be reported without accepting it for use.
"""
from contextlib import closing
import os
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import stat

from app import sqlite_disposable_maintenance_journal as journal

MAX_JOURNAL_BYTES = 1024 * 1024


def _file_identity(info):
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise RuntimeError("Unsafe retained fixture database")
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _require_no_sidecars(root, name="maintenance.db"):
    # A raw main-file image is not a committed snapshot when recovery/WAL state
    # exists. Never recover, checkpoint, delete or inspect those source files.
    for suffix in ("-journal", "-wal", "-shm"):
        if os.path.lexists(root / (name + suffix)):
            raise RuntimeError("Retained fixture has unresolved SQLite sidecars")


def _snapshot(root, name="maintenance.db"):
    """Read a bounded file image; SQLite never opens the source or sidecars."""
    _require_no_sidecars(root, name)
    path = root / name
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


def _copy_attempt(db, phase, history_valid):
    """Validate detached binding shape, without following its untrusted paths.

    A recorded checkpoint is not independent evidence of a media commit. Never
    open a media database or filesystem path supplied by the retained journal.
    """
    kinds = db.execute("SELECT type FROM sqlite_master WHERE lower(name)=?",
                       ("maintenance_copy_binding",)).fetchall()
    if not kinds:
        return None
    result = {"binding_status": "invalid_or_unavailable",
              "checkpoint": "unverified", "media_outcome": "not_independently_verified",
              "retry_authorized": False, "original_retention_verified": False}
    if kinds != [("table",)]:
        return result
    try:
        rows = db.execute("SELECT root, root_device, root_inode, database_device, "
                          "database_inode, operation_id FROM maintenance_copy_binding LIMIT 2").fetchall()
    except sqlite3.Error:
        return result
    if len(rows) != 1:
        return result
    root, *remaining = rows[0]
    identities, operation = remaining[:4], remaining[4]
    if (not isinstance(root, str) or not root.startswith('/') or '\x00' in root
            or str(PurePosixPath(root)) != root or '..' in PurePosixPath(root).parts
            or not all(type(value) is int and value >= 0 for value in identities)
            or not isinstance(operation, str) or operation in ('.', '..')
            or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', operation)):
        return result
    result['binding_status'] = 'structurally_valid_identifiers_only'
    if history_valid:
        result['checkpoint'] = ('outcomes_recorded' if phase == 'outcomes_verified'
                                else 'work_pending' if phase == 'work_pending'
                                else 'unexpected_maintenance_phase')
    return result


def _review_media_binding(db, media_root):
    """Read only an explicitly selected marked media lab, never a stored path."""
    root = Path(media_root)
    if not root.is_absolute() or root.resolve() != root or not stat.S_ISDIR(root.lstat().st_mode):
        raise RuntimeError('Canonical disposable media root required')
    directory = root.lstat()
    def marker():
        path = root / '.sqlite_disposable_rehearsal'
        expected = _file_identity(path.lstat())
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            if (_file_identity(os.fstat(fd)) != expected
                    or os.read(fd, 17) != b'DISPOSABLE ONLY\n'
                    or _file_identity(path.lstat()) != expected):
                raise RuntimeError('Disposable media marker unavailable')
        finally:
            os.close(fd)
        return expected
    marker_identity = marker()
    content, identity = _snapshot(root, 'state.db')
    report = {'binding': 'changed_or_unavailable', 'pending_operation': 'unverified',
              'source': 'detached_media_snapshot', 'retry_authorized': False,
              'media_bytes_verified': False, 'original_retention_verified': False}
    # Do not interpret media state as belonging to the attempt on identity drift.
    rows = db.execute('SELECT root, root_device, root_inode, database_device, '
                      'database_inode, operation_id FROM maintenance_copy_binding LIMIT 2').fetchall()
    expected = (str(root), directory.st_dev, directory.st_ino, identity[0], identity[1])
    if len(rows) == 1 and rows[0][:5] == expected:
        report['binding'] = 'matching_identifiers_only'
        with closing(sqlite3.connect(':memory:')) as media:
            media.deserialize(content)
            media.execute('PRAGMA query_only=ON')
            media.execute('PRAGMA trusted_schema=OFF')
            media.execute('PRAGMA temp_store=MEMORY')
            # Read only the schema/completion and pending record, not titles or
            # clocks. Absence of a pending record never proves a media commit.
            schema = media.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchall()
            complete = media.execute("SELECT value FROM metadata WHERE key='snapshot_complete'").fetchall()
            if schema != [('2',)] or complete != [('1',)]:
                raise RuntimeError('Completed media schema required')
            pending = media.execute("SELECT value_json FROM extra_state WHERE key='sqlite_pending_operations'").fetchall()
            if not pending:
                report['pending_operation'] = 'no_pending_record_not_completion_proof'
            elif len(pending) == 1:
                value = json.loads(pending[0][0])
                if not isinstance(value, dict) or not isinstance(value.get('id'), str):
                    raise RuntimeError('Pending media operation unavailable')
                report['pending_operation'] = ('matching_operation_requires_review'
                    if value['id'] == rows[0][5] else 'different_operation_requires_review')
            else:
                raise RuntimeError('Pending media operation unavailable')
    current = root.lstat()
    _require_no_sidecars(root, 'state.db')
    if ((current.st_dev, current.st_ino) != (directory.st_dev, directory.st_ino)
            or _file_identity((root/'state.db').lstat()) != identity
            or marker() != marker_identity):
        raise RuntimeError('Media evidence changed during review')
    return report


def review_disposable_maintenance(root, *, media_root=None):
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
        attempt = _copy_attempt(db, report['phase'], report['history_valid'])
        if attempt is not None:
            report["maintenance_copy_attempt_present"] = True
            report["copy_attempt"] = attempt
            report["blockers"].append("retained_media_attempt_requires_review")
            if attempt['binding_status'] == 'invalid_or_unavailable':
                report['blockers'].append('retained_media_binding_invalid_or_unavailable')
        if media_root is not None:
            if attempt is None or attempt['binding_status'] != 'structurally_valid_identifiers_only':
                raise RuntimeError('Valid retained attempt required for media comparison')
            report['media_comparison'] = _review_media_binding(db, media_root)
            report['blockers'].append('detached_media_comparison_never_authorizes_recovery')
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
