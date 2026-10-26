"""Capture a NEW private logical preview backup; never update or restore services.

This is a bounded observation of the frozen preview, not a writer-exclusion
permit or a physical SQLite database backup. Partial packets remain for review.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from app.sqlite_disposable_restore import _write_private
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_preview_install import _private_root
from app.sqlite_release_preparation import _identity
from app.sqlite_release_recovery import _encode, _local
from app.sqlite_scheduled_paths import _open_directory, scan_held_directory
from app.sqlite_state import SECTIONS, validate_snapshot

FILES = ('current.inspect.json', 'current-template.xml', 'saved-config.json',
         'retained-source.json', 'current-binding.json', 'tracking-snapshot.json')


def _boundary(phase):
    """Fault injection seam; no production side effects."""


def capture_backup(*, directory, expected_identity, container, template, source_revision,
                   validate_current, read_snapshot, read_inputs):
    if not re.fullmatch('[0-9a-f]{40}', source_revision or ''):
        raise ValueError('Current immutable source required')
    if (container.get('Name') != '/media_collection_auditor'
            or not re.fullmatch('[0-9a-f]{64}', container.get('Id', ''))
            or not re.fullmatch('sha256:[0-9a-f]{64}', container.get('Image', ''))):
        raise ValueError('Exact current container required')
    validate_current()
    state, revision = read_snapshot()
    validate_snapshot(state)
    if revision != 0 or INTENTS_KEY in state:
        raise RuntimeError('Frozen preview without pending operation required')
    before = read_inputs()
    if set(before) != {'saved-config.json', 'retained-source.json', 'current-binding.json'}:
        raise ValueError('Complete private source inputs required')
    payloads = {name: raw for name, (raw, _) in before.items()}
    payloads.update({'current.inspect.json': _encode(container), 'current-template.xml': template,
                     'tracking-snapshot.json': _encode(state)})
    if any(not isinstance(raw, bytes) or len(raw) > 64 * 1024 * 1024 for raw in payloads.values()):
        raise ValueError('Bounded private input bytes required')
    packet = Path(directory)
    fd = _private_root(packet, expected_identity)
    try:
        with scan_held_directory(fd) as entries:
            if next(entries, None) is not None:
                raise RuntimeError('New empty backup directory required; no retry or overwrite')
        _write_private(fd, 'backup-request.json', _encode({'schema_version': 1,
            'source_revision': source_revision, 'container_id': container['Id'],
            'image_id': container['Image'], 'media_actions_authorized': False}))
        _boundary('after_request')
        for name in FILES:
            _write_private(fd, name, payloads[name])
            _boundary('after_' + name)
        validate_current()
        if read_inputs() != before or read_snapshot() != (state, revision):
            raise RuntimeError('Current preview changed during capture')
        reopened = _private_root(packet, expected_identity)
        os.close(reopened)
        if any(_local(fd, name)[0] != payloads[name] for name in FILES):
            raise RuntimeError('Captured private backup changed')
        request_raw = _local(fd, 'backup-request.json')[0]
        receipt = {'schema_version': 1, 'status': 'preview_update_backup_captured',
            'backup_kind': 'logical_tracking_and_settings', 'source_revision': source_revision,
            'container_id': container['Id'], 'image_id': container['Image'], 'snapshot_revision': revision,
            'request_sha256': hashlib.sha256(request_raw).hexdigest(),
            'sha256': {name: hashlib.sha256(raw).hexdigest() for name, raw in payloads.items()},
            'tracking_counts': {key: len(state.get(key, {})) for key in SECTIONS},
            'service_changes_performed': False, 'media_actions_authorized': False,
            'update_authorized': False, 'automatic_restoration': False, 'writer_quiescence_verified': False}
        _boundary('before_completion')
        _write_private(fd, 'backup-complete.json', _encode(receipt))
        return {key: value for key, value in receipt.items() if key not in ('sha256', 'request_sha256')}
    finally:
        os.close(fd)


def capture_current(*, directory, expected_identity, container, templates):
    """Use only the CURRENT image's packaged validator and authoritative snapshot."""
    import runpy
    from app.sqlite_preview_activation import _revision, validate_preview_activation
    from app.state_store import GuardedSQLiteStateStore
    # The checker is pure source code, loaded without shadowing packaged app/profile.
    review_code = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'app/unraid_update_review.py'))
    review = review_code['review_update'](templates=templates, container=container)
    if review['blockers']:
        raise RuntimeError('Matching current template review required')
    matches = review_code['matching_templates'](templates)
    name = matches[0][0]
    template = next(raw for filename, raw in templates if filename == name)
    settings = dict(item.split('=', 1) for item in container['Config']['Env'])
    database = Path(settings.get('SQLITE_STATE_FILE', ''))
    paths = {'saved-config.json': Path(settings.get('WEB_CONFIG_FILE', '/app/logs/auditor_config.json')),
             'retained-source.json': Path(settings.get('STATE_FILE', '/app/logs/auditor_state.json')),
             'current-binding.json': database.parent / 'preview-release.json'}
    if any(not path.is_absolute() for path in (*paths.values(), database)):
        raise ValueError('Absolute current paths required')
    if any(Path(directory) == path or Path(directory) in path.parents or path in Path(directory).parents
           for path in (*paths.values(), database.parent)):
        raise ValueError('New disjoint backup directory required')
    def read_inputs():
        result = {}
        for key, path in paths.items():
            parent = _open_directory(str(path.parent))
            try:
                raw, info = _local(parent, path.name)
                result[key] = raw, _identity(info)
            finally:
                os.close(parent)
        return result
    def validator():
        validate_preview_activation(settings=settings)
    return capture_backup(directory=directory, expected_identity=expected_identity,
        container=container, template=template, source_revision=_revision(), validate_current=validator,
        read_snapshot=GuardedSQLiteStateStore(database).load_with_revision, read_inputs=read_inputs)


def inspect_backup(*, directory, expected_identity, expected_fingerprint):
    """Verify one explicitly selected complete packet; never adopt a partial one."""
    from app.sqlite_json import parse_unique_json
    if not re.fullmatch('[0-9a-f]{64}', expected_fingerprint or ''):
        raise ValueError('Exact backup receipt fingerprint required')
    fd = _private_root(Path(directory), expected_identity)
    try:
        raw, receipt_info = _local(fd, 'backup-complete.json')
        if hashlib.sha256(raw).hexdigest() != expected_fingerprint:
            raise RuntimeError('Selected backup receipt changed')
        receipt = parse_unique_json(raw)
        if (receipt.get('schema_version') != 1 or receipt.get('status') != 'preview_update_backup_captured'
                or receipt.get('snapshot_revision') != 0 or receipt.get('update_authorized') is not False
                or receipt.get('backup_kind') != 'logical_tracking_and_settings'
                or set(receipt.get('sha256', {})) != set(FILES)):
            raise RuntimeError('Complete known backup receipt required')
        request, request_info = _local(fd, 'backup-request.json')
        if hashlib.sha256(request).hexdigest() != receipt.get('request_sha256'):
            raise RuntimeError('Backup request changed')
        captured = {}
        for name in FILES:
            data, info = _local(fd, name)
            if hashlib.sha256(data).hexdigest() != receipt['sha256'][name]:
                raise RuntimeError('Backup content changed')
            captured[name] = data, _identity(info)
        state = parse_unique_json(captured['tracking-snapshot.json'][0]); validate_snapshot(state)
        if INTENTS_KEY in state:
            raise RuntimeError('Pending operation in backup')
        for name, value in captured.items():
            data, info = _local(fd, name)
            if (data, _identity(info)) != value:
                raise RuntimeError('Backup changed during inspection')
        current, info = _local(fd, 'backup-complete.json')
        if current != raw or _identity(info) != _identity(receipt_info):
            raise RuntimeError('Backup receipt replaced')
        current, info = _local(fd, 'backup-request.json')
        if current != request or _identity(info) != _identity(request_info):
            raise RuntimeError('Backup request replaced')
        reopened = _private_root(Path(directory), expected_identity); os.close(reopened)
        return {'status': 'preview_update_backup_verified', 'backup_kind': 'logical_tracking_and_settings',
                'update_authorized': False, 'automatic_restoration': False,
                'tracking_counts': {key: len(state.get(key, {})) for key in SECTIONS}}
    finally:
        os.close(fd)
