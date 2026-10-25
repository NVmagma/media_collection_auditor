"""Backup-first release preparation; never select a backend or control services.

Use only after quiescing every auditor state writer. The adjacent advisory lock
coordinates current writers; it cannot stop an older/noncooperating process.
Every destination is new and partial artifacts are retained without retry.
Linux descriptor paths anchor SQLite writes to the newly created private tree.
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys

from app.sqlite_disposable_restore import _write_private
from app.sqlite_json import parse_unique_json
from app.sqlite_lock import _exclusive_lock
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_scheduled_paths import _canonical, _open_directory
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import validate_snapshot
from app.state_store import GuardedSQLiteStateStore

REQUEST = 'preparation-request.json'
COMPLETE = 'preparation-complete.json'
BACKUP = 'original-state.json'
LIMIT = 64 * 1024 * 1024


def _protected_parent(path, expected):
    """Refuse ancestor chains where an ordinary user can redirect SQL paths.

    SQLite may canonicalize a descriptor path internally. Root/current-user
    ownership and non-writable (or trusted sticky) ancestors protect that path
    against other users; privileged administrators remain trusted by the model.
    No existing permissions are changed to make this check pass.
    """
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK
    fd = os.open('/', flags)
    try:
        def check(info):
            if (info.st_uid not in (0, os.geteuid())
                    or (info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX)):
                raise RuntimeError('Protected release control ancestors required')
        check(os.fstat(fd))
        for part in path.parts[1:]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd); fd = child
            check(os.fstat(fd))
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) != expected:
            raise RuntimeError('Release control parent identity changed')
    finally:
        os.close(fd)


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_nlink)


def _read(fd):
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= LIMIT:
        raise RuntimeError('Bounded regular single-link release input required')
    chunks, offset = [], 0
    while offset <= LIMIT:
        chunk = os.pread(fd, min(1024 * 1024, LIMIT + 1 - offset), offset)
        if not chunk:
            break
        chunks.append(chunk); offset += len(chunk)
    payload = b''.join(chunks)
    if len(payload) != info.st_size or _identity(os.fstat(fd)) != _identity(info):
        raise RuntimeError('Release input changed during read')
    return payload, info


def prepare_release_state(*, source, control_directory, expected_source_sha256):
    """Create a new backed-up state.db and durable nonauthorizing receipt.

    An exact expected source hash is mandatory. Never reuse an existing control
    directory, overwrite JSON, clear intents, start services or activate SQLite.
    The CLI performs only this preparation body. Executing it on production state
    is part of the final cutover review/approval, not authorized by fixture success.
    """
    if sys.platform != 'linux':
        raise RuntimeError('Linux descriptor-bound release preparation required')
    if not isinstance(expected_source_sha256, str) or not re.fullmatch('[0-9a-f]{64}', expected_source_sha256):
        raise ValueError('Explicit source SHA-256 required')
    source = Path(_canonical(str(source)))
    control = Path(_canonical(str(control_directory)))
    if source == control or control in source.parents:
        raise ValueError('Source must be outside the new control directory')
    with ExitStack() as stack:
        parents = {}
        for path in (source.parent, control.parent):
            if path not in parents:
                fd = _open_directory(str(path)); stack.callback(os.close, fd)
                parents[path] = fd
        source_parent = parents[source.parent]
        control_parent = parents[control.parent]
        parent_ids = {path: (os.fstat(fd).st_dev, os.fstat(fd).st_ino)
                      for path, fd in parents.items()}
        def verify_parents():
            _protected_parent(control.parent, parent_ids[control.parent])
            for path, expected in parent_ids.items():
                fd = _open_directory(str(path))
                try:
                    info = os.fstat(fd)
                    if (info.st_dev, info.st_ino) != expected:
                        raise RuntimeError('Release parent directory changed')
                finally:
                    os.close(fd)
        lock = Path(f'/proc/self/fd/{source_parent}') / (source.name + '.migration.lock')
        verify_lock = stack.enter_context(_exclusive_lock(lock, 'Release source writer is active'))
        source_fd = os.open(source.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=source_parent)
        stack.callback(os.close, source_fd)
        original, initial = _read(source_fd)
        digest = hashlib.sha256(original).hexdigest()
        if digest != expected_source_sha256:
            raise RuntimeError('Release source hash mismatch')
        state = parse_unique_json(original)
        # Reject NaN/Infinity even in unknown fields before any destination write.
        json.dumps(state, allow_nan=False)
        validate_snapshot(state)
        if INTENTS_KEY in state:
            raise RuntimeError('Unresolved operation prevents release preparation')
        def verify_source():
            verify_parents(); verify_lock()
            info = os.stat(source.name, dir_fd=source_parent, follow_symlinks=False)
            payload, held = _read(source_fd)
            if _identity(info) != _identity(initial) or _identity(held) != _identity(initial) or payload != original:
                raise RuntimeError('Release source identity/content changed')
        verify_source()
        os.mkdir(control.name, mode=0o700, dir_fd=control_parent)
        os.fsync(control_parent)
        control_fd = os.open(control.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                             dir_fd=control_parent)
        stack.callback(os.close, control_fd)
        created = os.fstat(control_fd)
        def verify_control():
            verify_source()
            info = os.stat(control.name, dir_fd=control_parent, follow_symlinks=False)
            held = os.fstat(control_fd)
            if (not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700
                    or info.st_uid != os.geteuid()
                    or (info.st_dev, info.st_ino) != (created.st_dev, created.st_ino)
                    or (held.st_dev, held.st_ino) != (created.st_dev, created.st_ino)):
                raise RuntimeError('New private release control directory changed')
        verify_control()
        request = {'schema_version': 1, 'request_id': secrets.token_hex(32),
            'source_sha256': digest, 'source_bytes': len(original),
            'source_identity': list(_identity(initial)),
            'control_identity': [created.st_dev, created.st_ino],
            'production_authorized': False, 'production_activation': 'disabled'}
        encode = lambda value: json.dumps(value, sort_keys=True, allow_nan=False).encode('ascii') + b'\n'
        request_payload = encode(request)
        _write_private(control_fd, REQUEST, request_payload)
        request_fd = os.open(REQUEST, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=control_fd)
        stack.callback(os.close, request_fd)
        if _read(request_fd)[0] != request_payload:
            raise RuntimeError('Release preparation request mismatch')
        request_info = os.fstat(request_fd)
        verify_control()
        _write_private(control_fd, BACKUP, original)
        verify_control()
        anchor = Path(f'/proc/self/fd/{control_fd}')
        backup_fd = os.open(BACKUP, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=control_fd)
        stack.callback(os.close, backup_fd)
        backup, backup_info = _read(backup_fd)
        if backup != original:
            raise RuntimeError('Release backup parity mismatch')
        write_offline_snapshot(state, anchor / 'state.db')
        verify_control()
        database_fd = os.open('state.db', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=control_fd)
        stack.callback(os.close, database_fd)
        os.fchmod(database_fd, 0o600); os.fsync(database_fd)
        database_info = os.fstat(database_fd)
        if not stat.S_ISREG(database_info.st_mode) or database_info.st_nlink != 1:
            raise RuntimeError('Private regular release database required')
        if GuardedSQLiteStateStore(anchor / 'state.db').load_with_revision() != (state, 0):
            raise RuntimeError('Release database parity/revision mismatch')
        verify_control()
        if (_read(backup_fd)[0] != original
                or _read(request_fd)[0] != request_payload
                or _identity(os.stat(REQUEST, dir_fd=control_fd, follow_symlinks=False)) != _identity(request_info)
                or _identity(os.stat(BACKUP, dir_fd=control_fd, follow_symlinks=False)) != _identity(backup_info)
                or _identity(os.stat('state.db', dir_fd=control_fd, follow_symlinks=False)) != _identity(database_info)):
            raise RuntimeError('Release output changed during verification')
        receipt = {**request, 'status': 'release_state_prepared_not_activated',
            'database_revision': 0, 'backup_verified': True, 'migration_parity': True,
            'writer_quiescence_verified': False, 'automatic_action': 'none'}
        _write_private(control_fd, COMPLETE, encode(receipt))
        verify_control()
        os.fsync(control_fd)
        return receipt


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--source', required=True)
    parser.add_argument('--new-control-directory', required=True)
    parser.add_argument('--expected-source-sha256', required=True)
    args = parser.parse_args(argv)
    try:
        report = prepare_release_state(source=args.source,
            control_directory=args.new_control_directory,
            expected_source_sha256=args.expected_source_sha256)
    except Exception as error:
        # File contents, private title keys and SQLite exception text never enter
        # stdout/stderr. Retained artifacts remain available for private review.
        print(json.dumps({'status': 'release_preparation_blocked',
            'failure_category': type(error).__name__, 'automatic_action': 'none',
            'production_authorized': False, 'production_activation': 'disabled'}))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
