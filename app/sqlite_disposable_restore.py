"""Publish a fresh JSON restore in a marked lab; never overwrite or activate.

Only a new restored-state-*.json basename is accepted. A durable request remains
on every outcome, so an interrupted operation cannot be automatically repeated.
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat

from app.sqlite_disposable_rollback import _candidate_name, _read_candidate, _snapshot
from app.sqlite_isolated_lifecycle_runner import isolated_runner_lock
from app.sqlite_lock import state_writer_lock
from app.sqlite_scheduled_paths import _open_directory
from app.sqlite_title_identity import validate_title_folder

REQUEST = '.sqlite_restore_request.json'
COMPLETE = '.sqlite_restore_complete.json'


def _write_private(parent, name, payload):
    fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
    try:
        remaining = memoryview(payload)
        while remaining:
            written = os.write(fd, remaining)
            if written <= 0: raise OSError('Restore write stopped')
            remaining = remaining[written:]
        os.fsync(fd)
        current = os.stat(name, dir_fd=parent, follow_symlinks=False)
        held = os.fstat(fd)
        if (not stat.S_ISREG(held.st_mode) or held.st_nlink != 1
                or (current.st_dev, current.st_ino) != (held.st_dev, held.st_ino)
                or os.pread(fd, len(payload) + 1, 0) != payload):
            raise RuntimeError('Private restore write could not be verified')
    finally:
        os.close(fd)
    os.fsync(parent)


def restore_disposable_json(*, root, candidate_name, output_name, fault_at=None):
    """Restore current tracking to a new private file; leave all originals intact.

    Publication uses a same-directory hard link with atomic no-overwrite
    semantics. Unsupported publication fails closed, with no copy/replace fallback.
    A completion record is written only after exact parity and current-source
    checks. Neither a request nor a completion permits production cutover.
    """
    root = Path(root)
    candidate_name = _candidate_name(candidate_name)
    output_name = validate_title_folder(output_name)
    if not output_name.startswith('restored-state-') or not output_name.endswith('.json'):
        raise ValueError('New private restored-state-*.json basename required')
    if fault_at not in (None, 'after_request', 'after_staging', 'after_publication'):
        raise ValueError('Unknown disposable restore fault boundary')
    with isolated_runner_lock(root) as verify_control, ExitStack() as stack:
        parent = _open_directory(str(root)); stack.callback(os.close, parent)
        # State writer locks cover both retained legacy JSON and the new output.
        verify_original_lock = stack.enter_context(state_writer_lock(root / 'original.json'))
        verify_output_lock = stack.enter_context(state_writer_lock(root / output_name))
        for name in (REQUEST, COMPLETE, output_name):
            try:
                os.stat(name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise RuntimeError('Existing restore artifact; no replay or overwrite')
        session, state, revision = _snapshot(root)
        held = {}
        originals = {}
        for name in ('state.db', 'original.json', 'original.backup.json', candidate_name):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            stack.callback(os.close, fd)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise RuntimeError('Regular private restore inputs required')
            held[name] = (fd, info)
            if name != 'state.db': originals[name] = (root / name).read_bytes()
        if originals['original.json'] != originals['original.backup.json']:
            raise RuntimeError('Retained original backup mismatch')
        if _read_candidate(parent, candidate_name) != state:
            raise RuntimeError('Stale or mismatched rollback candidate')

        def identity(info):
            return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)

        def verify():
            verify_control(); verify_original_lock(); verify_output_lock()
            session.read_verified_snapshot()
            for name, (fd, expected) in held.items():
                current = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if identity(current) != identity(expected) or identity(os.fstat(fd)) != identity(expected):
                    raise RuntimeError('Restore input identity/content changed')
                if name in originals and (root / name).read_bytes() != originals[name]:
                    raise RuntimeError('Retained restore input changed')
            if _read_candidate(parent, candidate_name) != state:
                raise RuntimeError('Restore candidate changed')

        verify()
        payload = json.dumps(state, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False).encode('ascii') + b'\n'
        request = {'version': 1, 'revision': revision, 'candidate_name': candidate_name,
            'output_name': output_name, 'snapshot_sha256': hashlib.sha256(payload).hexdigest(),
            'production_activation': 'disabled', 'production_authorized': False}
        request_payload = json.dumps(request, sort_keys=True).encode('ascii') + b'\n'
        _write_private(parent, REQUEST, request_payload)
        request_fd = os.open(REQUEST, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        stack.callback(os.close, request_fd)
        held[REQUEST] = (request_fd, os.fstat(request_fd))
        originals[REQUEST] = request_payload
        if fault_at == 'after_request': raise RuntimeError('Injected restore fault after request')
        staging = '.restore-staging-' + secrets.token_hex(16) + '.json'
        _write_private(parent, staging, payload)
        stage_fd = os.open(staging, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        stage_handle = stack.enter_context(os.fdopen(stage_fd, 'rb'))
        expected_stage = os.fstat(stage_fd)
        if _read_candidate(parent, staging) != state:
            raise RuntimeError('Staged restore parity mismatch')
        if fault_at == 'after_staging': raise RuntimeError('Injected restore fault after staging')
        verify()
        if identity(os.stat(staging, dir_fd=parent, follow_symlinks=False)) != identity(expected_stage):
            raise RuntimeError('Restore staging changed')
        os.link(staging, output_name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
        os.fsync(parent)
        if fault_at == 'after_publication': raise RuntimeError('Injected restore fault after publication')
        current_stage = os.stat(staging, dir_fd=parent, follow_symlinks=False)
        current_output = os.stat(output_name, dir_fd=parent, follow_symlinks=False)
        if (current_stage.st_nlink != 2 or current_output.st_nlink != 2
                or (current_output.st_dev, current_output.st_ino) != (expected_stage.st_dev, expected_stage.st_ino)
                or (current_stage.st_dev, current_stage.st_ino) != (expected_stage.st_dev, expected_stage.st_ino)):
            raise RuntimeError('Published restore identity mismatch')
        # FUSE may retain an unlinked open file under a hidden name. Close this
        # inode's last file descriptor before removing our staging link; keep
        # the parent/control/input descriptors pinned and all parity checks.
        # File-object close is idempotent when ExitStack later unwinds.
        stage_handle.close()
        stage_before_unlink = os.stat(staging, dir_fd=parent, follow_symlinks=False)
        if (not stat.S_ISREG(stage_before_unlink.st_mode) or stage_before_unlink.st_nlink != 2
                or (stage_before_unlink.st_dev, stage_before_unlink.st_ino) !=
                   (expected_stage.st_dev, expected_stage.st_ino)):
            raise RuntimeError('Restore staging changed before unlink')
        # Remove only this attempt's own staging link after verified publication.
        os.unlink(staging, dir_fd=parent)
        os.fsync(parent)
        verify()
        if _read_candidate(parent, output_name) != state:
            raise RuntimeError('Published restore parity mismatch')
        _write_private(parent, COMPLETE, json.dumps({**request, 'status': 'disposable_restore_verified'},
            sort_keys=True).encode('ascii') + b'\n')
        verify()
        return {'status': 'disposable_restore_verified', 'revision': revision,
            'fresh_snapshot_parity': True, 'original_backup_unchanged': True,
            'automatic_retry': False, 'fixture_only': True, 'production_restore_performed': False,
            'production_activation': 'disabled', 'production_authorized': False}
