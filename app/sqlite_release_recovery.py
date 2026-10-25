"""Export/inspect latest tracking for recovery; never overwrite or activate.

Caller must stop all auditor writers. Locks coordinate current worker/migration
code, but do not establish quiescence of old or noncooperating processes. Every
export is a new private candidate; incomplete attempts are retained, never used.
"""
from contextlib import ExitStack, contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_disposable_restore import _write_private
from app.sqlite_json import parse_unique_json
from app.sqlite_lock import _exclusive_lock
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_release_preparation import (BACKUP, COMPLETE, REQUEST, LIMIT,
    _identity, _protected_parent, _read)
from app.sqlite_scheduled_paths import _canonical, _open_directory
from app.sqlite_state import validate_snapshot
from app.state_store import GuardedSQLiteStateStore


def _encode(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('ascii') + b'\n'


def _local(parent, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        raw, info = _read(fd)
        if _identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != _identity(info):
            raise RuntimeError('Recovery artifact changed during read')
        return raw, info
    finally:
        os.close(fd)


def _name(value):
    if not isinstance(value, str) or not re.fullmatch(r'rollback-candidate-[a-z0-9-]{1,64}\.json', value):
        raise ValueError('Explicit new private rollback candidate basename required')
    return value


@contextmanager
def _prepared_snapshot(source, control_directory):
    if sys.platform != 'linux':
        raise RuntimeError('Linux descriptor-bound release recovery required')
    source, control = Path(_canonical(str(source))), Path(_canonical(str(control_directory)))
    if source == control or control in source.parents:
        raise ValueError('Distinct retained JSON source and control directory required')
    with ExitStack() as stack:
        parents = {}
        for path in (source.parent, control.parent):
            if path not in parents:
                fd = _open_directory(str(path)); stack.callback(os.close, fd)
                parents[path] = fd
        parent_ids = {p: (os.fstat(fd).st_dev, os.fstat(fd).st_ino) for p, fd in parents.items()}
        _protected_parent(control.parent, parent_ids[control.parent])
        source_parent, control_parent = parents[source.parent], parents[control.parent]
        control_fd = os.open(control.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=control_parent)
        stack.callback(os.close, control_fd)
        initial_control = os.fstat(control_fd)
        if stat.S_IMODE(initial_control.st_mode) != 0o700 or initial_control.st_uid != os.geteuid():
            raise RuntimeError('Private release control directory required')
        source_lock = Path(f'/proc/self/fd/{source_parent}') / (source.name + '.migration.lock')
        verify_source_lock = stack.enter_context(_exclusive_lock(source_lock, 'Recovery source writer is active'))
        anchor = Path(f'/proc/self/fd/{control_fd}')
        verify_control_lock = stack.enter_context(_exclusive_lock(anchor / '.sqlite_runner.lock',
            'Another scheduled worker or recovery is active'))
        held = {}
        for label, parent, name in (('source', source_parent, source.name),
                ('backup', control_fd, BACKUP), ('request', control_fd, REQUEST),
                ('receipt', control_fd, COMPLETE)):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            stack.callback(os.close, fd)
            raw, info = _read(fd)
            held[label] = (fd, parent, name, raw, info)
        original = held['source'][3]
        request = parse_unique_json(held['request'][3])
        receipt = parse_unique_json(held['receipt'][3])
        if not isinstance(request, dict) or not isinstance(receipt, dict):
            raise RuntimeError('Release preparation receipts required')
        if (type(request.get('schema_version')) is not int or request['schema_version'] != 1
                or not isinstance(request.get('request_id'), str)
                or not re.fullmatch('[0-9a-f]{64}', request['request_id'])
                or request.get('source_sha256') != hashlib.sha256(original).hexdigest()
                or type(request.get('source_bytes')) is not int or request['source_bytes'] != len(original)
                or request.get('source_identity') != list(_identity(held['source'][4]))
                or request.get('control_identity') != [initial_control.st_dev, initial_control.st_ino]
                or held['backup'][3] != original
                or any(receipt.get(key) != value for key, value in request.items())
                or request.get('production_authorized') is not False
                or request.get('production_activation') != 'disabled'
                or receipt.get('production_authorized') is not False
                or receipt.get('status') != 'release_state_prepared_not_activated'
                or type(receipt.get('database_revision')) is not int or receipt['database_revision'] != 0
                or receipt.get('migration_parity') is not True or receipt.get('backup_verified') is not True
                or receipt.get('automatic_action') != 'none'
                or receipt.get('writer_quiescence_verified') is not False):
            raise RuntimeError('Release preparation binding mismatch')
        original_state = parse_unique_json(original)
        validate_snapshot(original_state); _encode(original_state)
        if INTENTS_KEY in original_state:
            raise RuntimeError('Retained JSON contains unresolved operation')
        database_fd = os.open('state.db', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=control_fd)
        stack.callback(os.close, database_fd)
        database_info = os.fstat(database_fd)
        if (not stat.S_ISREG(database_info.st_mode) or database_info.st_nlink != 1
                or receipt.get('database_identity') != [database_info.st_dev, database_info.st_ino]):
            raise RuntimeError('Prepared database identity changed or unbound')
        session = RevisionedAuditSession(GuardedSQLiteStateStore(anchor / 'state.db'))
        state, revision = session.read_verified_snapshot()
        validate_snapshot(state); _encode(state)
        if INTENTS_KEY in state:
            raise RuntimeError('Unresolved SQLite operation blocks release recovery')
        def verify():
            verify_source_lock(); verify_control_lock()
            _protected_parent(control.parent, parent_ids[control.parent])
            for path, expected in parent_ids.items():
                fd = _open_directory(str(path))
                try:
                    info = os.fstat(fd)
                    if (info.st_dev, info.st_ino) != expected:
                        raise RuntimeError('Recovery parent directory changed')
                finally:
                    os.close(fd)
            current = os.stat(control.name, dir_fd=control_parent, follow_symlinks=False)
            if (not stat.S_ISDIR(current.st_mode) or stat.S_IMODE(current.st_mode) != 0o700
                    or current.st_uid != os.geteuid()
                    or (current.st_dev, current.st_ino) != (initial_control.st_dev, initial_control.st_ino)):
                raise RuntimeError('Recovery control directory changed')
            for fd, parent, name, raw, info in held.values():
                if (_identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != _identity(info)
                        or _identity(os.fstat(fd)) != _identity(info) or _read(fd)[0] != raw):
                    raise RuntimeError('Retained release input changed')
            if (_identity(os.stat('state.db', dir_fd=control_fd, follow_symlinks=False)) != _identity(database_info)
                    or _identity(os.fstat(database_fd)) != _identity(database_info)):
                raise RuntimeError('Recovery database changed')
            session.read_verified_snapshot()
        verify()
        yield control_fd, state, revision, request['request_id'], verify
        verify()


def _report(revision, candidate_revision, matches):
    return {'status': 'release_candidate_current_advisory_only' if matches else 'blocked',
        'revision': revision, 'candidate_revision': candidate_revision,
        'reason': 'current_snapshot_matches' if matches else 'candidate_not_current',
        'restore_performed': False, 'automatic_action': 'none',
        'writer_quiescence_verified': False, 'production_authorized': False,
        'production_activation': 'disabled'}


def export_release_candidate(*, source, control_directory, candidate_name):
    name = _name(candidate_name)
    with _prepared_snapshot(source, control_directory) as (parent, state, revision, preparation_id, verify):
        for item in (name, name + '.request.json', name + '.complete.json'):
            try: os.stat(item, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError: continue
            raise RuntimeError('Existing recovery artifact; no overwrite or replay')
        payload = _encode(state)
        if len(payload) > LIMIT:
            raise RuntimeError('Bounded recovery snapshot required')
        request = {'schema_version': 1, 'preparation_id': preparation_id,
            'revision': revision, 'candidate_name': name,
            'snapshot_sha256': hashlib.sha256(payload).hexdigest(),
            'production_authorized': False, 'production_activation': 'disabled'}
        raw_request = _encode(request)
        _write_private(parent, name + '.request.json', raw_request)
        verify()
        _write_private(parent, name, payload)
        verify()
        if _local(parent, name)[0] != payload or _local(parent, name + '.request.json')[0] != raw_request:
            raise RuntimeError('Recovery export parity mismatch')
        raw_receipt = _encode({**request, 'status': 'release_candidate_exported_not_restored'})
        _write_private(parent, name + '.complete.json', raw_receipt)
        verify()
        for item, expected in ((name, payload), (name + '.request.json', raw_request),
                (name + '.complete.json', raw_receipt)):
            if _local(parent, item)[0] != expected:
                raise RuntimeError('Recovery export changed after publication')
        return _report(revision, revision, True)


def inspect_release_candidate(*, source, control_directory, candidate_name):
    name = _name(candidate_name)
    with _prepared_snapshot(source, control_directory) as (parent, state, revision, preparation_id, verify):
        captured = {item: _local(parent, item) for item in
            (name, name + '.request.json', name + '.complete.json')}
        raw = captured[name][0]
        request = parse_unique_json(captured[name + '.request.json'][0])
        receipt = parse_unique_json(captured[name + '.complete.json'][0])
        candidate = parse_unique_json(raw)
        validate_snapshot(candidate); _encode(candidate)
        if (not isinstance(request, dict) or not isinstance(receipt, dict)
                or type(request.get('schema_version')) is not int or request['schema_version'] != 1
                or request.get('preparation_id') != preparation_id or request.get('candidate_name') != name
                or type(request.get('revision')) is not int or request['revision'] < 0
                or request.get('snapshot_sha256') != hashlib.sha256(raw).hexdigest()
                or request.get('production_authorized') is not False
                or request.get('production_activation') != 'disabled'
                or any(receipt.get(key) != value for key, value in request.items())
                or receipt.get('production_authorized') is not False
                or receipt.get('status') != 'release_candidate_exported_not_restored'
                or INTENTS_KEY in candidate):
            raise RuntimeError('Complete bound recovery export required')
        verify()
        for item, (payload, info) in captured.items():
            current, current_info = _local(parent, item)
            if current != payload or _identity(current_info) != _identity(info):
                raise RuntimeError('Recovery candidate changed during inspection')
        return _report(revision, request['revision'], candidate == state and request['revision'] == revision)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('action', choices=('export', 'inspect'))
    parser.add_argument('--source', required=True)
    parser.add_argument('--control-directory', required=True)
    parser.add_argument('--candidate-name', required=True)
    args = parser.parse_args(argv)
    try:
        operation = export_release_candidate if args.action == 'export' else inspect_release_candidate
        report = operation(source=args.source, control_directory=args.control_directory, candidate_name=args.candidate_name)
    except Exception as error:
        print(json.dumps({'status': 'release_recovery_blocked', 'failure_category': type(error).__name__,
            'automatic_action': 'none', 'production_authorized': False, 'production_activation': 'disabled'}))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0 if report['status'] == 'release_candidate_current_advisory_only' else 1


if __name__ == '__main__':
    raise SystemExit(main())
