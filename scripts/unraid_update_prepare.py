"""Prepare a new preview binding from an explicitly selected verified backup.

Only new private directories are writable. No Docker, HTTP, template installation,
old-file modification, container start, automatic rollback or retry occurs here.
"""
from contextlib import ExitStack
import hashlib
import os
from pathlib import Path
import re

from app.config_store import KEYS, DEFAULTS
from app.sqlite_disposable_restore import _write_private
from app.sqlite_json import parse_unique_json
from app.sqlite_preview_activation import _revision, _policy, _roots, validate_preview_activation
from app.sqlite_preview_install import _private_root, stage_preview
from app.sqlite_preview_template import RUNTIME_DEFAULTS
from app.sqlite_release_recovery import _encode, _local
from app.sqlite_scheduled_paths import _canonical, scan_held_directory
from app.state_store import GuardedSQLiteStateStore
from scripts.unraid_update_backup import load_backup_payloads


REQUEST = 'update-preparation-request.json'
COMPLETE = 'update-preparation-complete.json'


def _boundary(phase):
    """Test interruption seam; partial directories remain retained."""


def prepare_replacement(*, backup, backup_identity, backup_fingerprint, logs, logs_identity,
                        control, control_identity, candidate_image):
    revision = _revision()  # Immutable profile from the candidate interpreter.
    config = candidate_image.get('Config', {})
    labels = config.get('Labels') or {}
    image_id = candidate_image.get('Id', '')
    if (not re.fullmatch('sha256:[0-9a-f]{64}', image_id)
            or labels.get('org.opencontainers.image.revision') != revision
            or labels.get('io.media-collection-auditor.sqlite-activation') != 'preview-only'
            or config.get('Entrypoint') != ['python', '-m', 'app.main']
            or config.get('Cmd') not in (None, []) or config.get('StopSignal') != 'SIGINT'
            or config.get('Volumes') not in (None, {})):
        raise ValueError('Matching packaged candidate image contract required')
    paths = [Path(_canonical(str(path))) for path in (backup, logs, control)]
    for index, path in enumerate(paths):
        if any(path == other or path in other.parents or other in path.parents for other in paths[index+1:]):
            raise ValueError('Disjoint backup/logs/control roots required')
    backup, logs, control = paths
    if len({backup_identity, logs_identity, control_identity}) != 3:
        raise ValueError('Distinct private directory identities required')
    selected = dict(directory=backup, expected_identity=backup_identity, expected_fingerprint=backup_fingerprint)
    payloads = load_backup_payloads(**selected)
    current = parse_unique_json(payloads['current.inspect.json'])
    saved = parse_unique_json(payloads['saved-config.json'])
    state = parse_unique_json(payloads['tracking-snapshot.json'])
    if not isinstance(saved, dict):
        raise ValueError('Saved configuration object required')
    env = {}
    for item in current['Config']['Env']:
        key, separator, value = item.partition('=')
        if (not separator or not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', key) or key in env
                or any(ord(char) < 32 or ord(char) == 127 for char in value)):
            raise ValueError('Losslessly representable unique environment required')
        if key not in RUNTIME_DEFAULTS:
            env[key] = value
    if any(env.get(key) for key in ('PYTHONHOME', 'PYTHONSTARTUP', 'LD_PRELOAD', 'LD_LIBRARY_PATH')):
        raise ValueError('Custom runtime environment requires review')
    env.update(STATE_FILE=str(logs/'auditor_state.json'), WEB_CONFIG_FILE=str(logs/'auditor_config.json'),
               SQLITE_STATE_FILE=str(control/'release'/'state.db'))
    # Preserve safety flags/schedule rather than silently replacing user policy.
    effective = {**{key: DEFAULTS.get(key, '') for key in KEYS}, **env,
                 **{key: str(value) for key, value in saved.items() if key in KEYS}}
    policy, _, _, _ = _policy(effective)
    _roots(policy, control_identity)
    with ExitStack() as stack:
        log_fd = _private_root(logs, logs_identity); stack.callback(os.close, log_fd)
        control_fd = _private_root(control, control_identity); stack.callback(os.close, control_fd)
        for fd in (log_fd, control_fd):
            with scan_held_directory(fd) as entries:
                if next(entries, None) is not None:
                    raise RuntimeError('New empty replacement roots required; partial attempts cannot replay')
        _write_private(log_fd, REQUEST, _encode({'schema_version': 1, 'source_revision': revision,
            'candidate_image_id': image_id, 'backup_fingerprint': backup_fingerprint,
            'update_authorized': False, 'media_actions_authorized': False}))
        _boundary('after_request')
        _write_private(log_fd, 'auditor_state.json', payloads['tracking-snapshot.json'])
        _write_private(log_fd, 'auditor_config.json', payloads['saved-config.json'])
        _boundary('before_binding')
        stage_preview(source=logs/'auditor_state.json', config=logs/'auditor_config.json',
            control_root=control, expected_control_identity=control_identity,
            expected_config_sha256=hashlib.sha256(payloads['saved-config.json']).hexdigest(),
            proposed_config=saved, settings=env)
        _boundary('after_binding')
        validate_preview_activation(settings=env)
        if GuardedSQLiteStateStore(control/'release'/'state.db').load_with_revision() != (state, 0):
            raise RuntimeError('Replacement tracking parity changed')
        if parse_unique_json(_local(log_fd, 'auditor_config.json')[0]) != saved:
            raise RuntimeError('Replacement settings changed')
        if load_backup_payloads(**selected) != payloads:
            raise RuntimeError('Selected backup changed during preparation')
        for path, identity in ((logs, logs_identity), (control, control_identity)):
            reopened = _private_root(path, identity); os.close(reopened)
        _write_private(log_fd, 'runtime.env', ''.join(key+'='+value+'\n' for key,value in sorted(env.items())).encode())
        report = {'schema_version': 1, 'status': 'replacement_preview_binding_prepared',
            'source_revision': revision, 'candidate_image_id': image_id,
            'backup_fingerprint': backup_fingerprint, 'tracking_preserved': True,
            'settings_preserved': True, 'snapshot_revision': 0,
            'service_changes_performed': False, 'media_actions_authorized': False,
            'update_authorized': False, 'automatic_restoration': False,
            'backup_freshness_verified': False}
        _boundary('before_completion')
        _write_private(log_fd, COMPLETE, _encode(report))
        return report
