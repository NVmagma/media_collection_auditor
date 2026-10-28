"""Capture a NEW private logical preview backup; never update or restore services.

This is a bounded observation of the frozen preview, not a writer-exclusion
permit or a physical SQLite database backup. Partial packets remain for review.
"""
import hashlib
from datetime import datetime, timezone
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
                   validate_current, read_snapshot, read_inputs, reviewed_settings_change=None):
    if reviewed_settings_change not in (None, 'enable_tv_preview'):
        raise ValueError('Known explicitly reviewed settings change required')
    if not re.fullmatch('[0-9a-f]{40}', source_revision or ''):
        raise ValueError('Current immutable source required')
    if (container.get('Name') != '/media_collection_auditor'
            or not re.fullmatch('[0-9a-f]{64}', container.get('Id', ''))
            or not re.fullmatch('sha256:[0-9a-f]{64}', container.get('Image', ''))):
        raise ValueError('Exact current container required')
    validate_current()
    state, revision = read_snapshot()
    validate_snapshot(state)
    if type(revision) is not int or revision != 0 or INTENTS_KEY in state:
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
            'image_id': container['Image'], 'media_actions_authorized': False,
            'reviewed_settings_change': reviewed_settings_change}))
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
            'captured_at': datetime.now(timezone.utc).isoformat(),
            'reviewed_settings_change': reviewed_settings_change,
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


def _local_read_path(path):
    parent = _open_directory(str(path.parent))
    try:
        return _local(parent, path.name)
    finally:
        os.close(parent)


def require_tv_only_change(prepared, selected, original_enabled='false'):
    if not isinstance(prepared, dict) or not isinstance(selected, dict):
        raise ValueError('Configuration objects required')
    before, after = dict(prepared), dict(selected)
    old, new = before.pop('ENABLE_TV', original_enabled), after.pop('ENABLE_TV', None)
    if (str(old).lower() != 'false' or str(new).lower() != 'true' or before != after):
        raise RuntimeError('Only the explicitly reviewed TV enable change is permitted')


def capture_current(*, directory, expected_identity, container, templates, selected_settings=None):
    """Use only the CURRENT image's packaged validator and authoritative snapshot."""
    import runpy
    from app.sqlite_preview_activation import _revision, validate_preview_activation
    from app.state_store import GuardedSQLiteStateStore
    # The checker is pure source code, loaded without shadowing packaged app/profile.
    review_path = Path(__file__).resolve().parents[1] / 'app/unraid_update_review.py'
    if not review_path.is_file(): review_path = Path('/app/app/unraid_update_review.py')
    review_code = runpy.run_path(str(review_path))
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
    reviewed_change = None
    if selected_settings is not None:
        from app.config_store import KEYS, DEFAULTS
        from app.sqlite_json import parse_unique_json
        from app.sqlite_preview_activation import _effective, _policy, _roots
        if container.get('State', {}).get('Running') is not False:
            raise RuntimeError('Stopped original required for reviewed settings repair')
        original_settings, _ = _effective(settings)
        prepared_config = parse_unique_json(_local_read_path(paths['saved-config.json'])[0])
        selected_config = parse_unique_json(_local_read_path(Path(selected_settings))[0])
        require_tv_only_change(prepared_config, selected_config, original_settings.get('ENABLE_TV', 'false'))
        planned = {**{key: DEFAULTS.get(key, '') for key in KEYS}, **original_settings,
                   **{key: str(value) for key,value in selected_config.items() if key in KEYS}}
        policy, _, _, _ = _policy(planned)
        info = database.parent.stat()
        _roots(policy, (info.st_dev, info.st_ino))
        paths['saved-config.json'] = Path(selected_settings)
        reviewed_change = 'enable_tv_preview'
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
        read_snapshot=GuardedSQLiteStateStore(database).load_with_revision, read_inputs=read_inputs,
        reviewed_settings_change=reviewed_change)


def inspect_backup(*, directory, expected_identity, expected_fingerprint):
    """Compatibility entrypoint for the shared read-only packet inspector."""
    from app import sqlite_release_recovery
    inspector = getattr(sqlite_release_recovery, 'inspect_update_backup', None)
    if inspector is None:
        # Older deployed images lack this new shared helper. Load only trusted
        # reviewed checkout code; never select code from a backup or request.
        import runpy
        source = Path(__file__).resolve().parents[1] / 'app' / 'sqlite_release_recovery.py'
        inspector = runpy.run_path(str(source)).get('inspect_update_backup')
    if not callable(inspector):
        raise RuntimeError('Reviewed backup inspector unavailable')
    return inspector(directory=directory, expected_identity=expected_identity,
                     expected_fingerprint=expected_fingerprint)


def load_backup_payloads(*, directory, expected_identity, expected_fingerprint):
    """Private internal input for preparation; caller must never print payloads."""
    from app.sqlite_json import parse_unique_json
    inspect_backup(directory=directory, expected_identity=expected_identity, expected_fingerprint=expected_fingerprint)
    fd = _private_root(Path(directory), expected_identity)
    try:
        receipt_raw, _ = _local(fd, 'backup-complete.json')
        if hashlib.sha256(receipt_raw).hexdigest() != expected_fingerprint:
            raise RuntimeError('Selected backup changed before loading')
        receipt = parse_unique_json(receipt_raw)
        payloads = {name: _local(fd, name)[0] for name in FILES}
        if any(hashlib.sha256(raw).hexdigest() != receipt['sha256'][name] for name, raw in payloads.items()):
            raise RuntimeError('Backup changed before preparation')
    finally:
        os.close(fd)
    inspect_backup(directory=directory, expected_identity=expected_identity, expected_fingerprint=expected_fingerprint)
    return payloads


def main():
    """Capture current frozen preview into an explicitly new private host packet."""
    import argparse
    from app.sqlite_json import parse_unique_json
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--directory', required=True)
    parser.add_argument('--identity', required=True)
    parser.add_argument('--templates', required=True)
    parser.add_argument('--selected-settings')
    args = parser.parse_args()
    try:
        if not re.fullmatch('[0-9]+:[0-9]+', args.identity):
            raise ValueError('Expected packet identity required')
        expected = tuple(map(int, args.identity.split(':')))
        raw = sys.stdin.buffer.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024: raise ValueError('Bounded inspect input required')
        items = parse_unique_json(raw)
        if not isinstance(items, list) or len(items) != 1: raise ValueError('Single current container required')
        folder = _open_directory(args.templates)
        try:
            templates = [(name, _local(folder,name)[0]) for name in sorted(os.listdir(folder)) if name.endswith('.xml')]
        finally:
            os.close(folder)
        result = capture_current(directory=args.directory, expected_identity=expected, container=items[0], templates=templates, selected_settings=args.selected_settings)
        receipt_fd = _private_root(Path(args.directory), expected)
        try: fingerprint = hashlib.sha256(_local(receipt_fd,'backup-complete.json')[0]).hexdigest()
        finally: os.close(receipt_fd)
        result['backup_fingerprint'] = fingerprint
    except Exception as error:
        result = {'status': 'preview_update_backup_blocked', 'error_type': type(error).__name__,
                  'automatic_action': 'none', 'service_changes_performed': False,
                  'media_actions_authorized': False, 'partial_files_retained': True}
        print(json.dumps(result, sort_keys=True)); return 2
    print(json.dumps(result, sort_keys=True)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
