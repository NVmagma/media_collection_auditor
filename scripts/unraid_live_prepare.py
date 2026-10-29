"""Prepare a new live canary binding from a selected logical preview backup.

Only new private directories are writable. No Docker, HTTP, template installation,
old-file modification, container start, automatic rollback or retry occurs here.
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re

from app.config_store import KEYS, DEFAULTS
from app.sqlite_disposable_restore import _write_private
from app.sqlite_json import parse_unique_json
from app.sqlite_live_binding import _revision, _policy, _media, create_live_binding, validate_live_binding
from app.sqlite_live_policy import DISABLED
from app.sqlite_preview_install import _private_root
from app.sqlite_release_preparation import prepare_release_state
from app.sqlite_preview_template import RUNTIME_DEFAULTS
from app.sqlite_release_recovery import _encode, _local
from app.sqlite_scheduled_paths import _canonical, scan_held_directory
from app.state_store import GuardedSQLiteStateStore
from scripts.unraid_update_backup import load_backup_payloads


REQUEST = 'live-preparation-request.json'
COMPLETE = 'live-preparation-complete.json'


def _boundary(phase):
    """Test interruption seam; partial directories remain retained."""


def prepare_live_candidate(*, backup, backup_identity, backup_fingerprint, logs, logs_identity,
                        control, control_identity, candidate_image):
    revision = _revision()  # Immutable profile from the candidate interpreter.
    config = candidate_image.get('Config', {})
    labels = config.get('Labels') or {}
    image_id = candidate_image.get('Id', '')
    if (not re.fullmatch('sha256:[0-9a-f]{64}', image_id)
            or labels.get('org.opencontainers.image.revision') != revision
            or labels.get('io.media-collection-auditor.sqlite-activation') != 'scheduled-moves'
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
    # These are the only reviewed canary changes. Preserve library selection,
    # credentials, schedule, paths, lifecycle clocks and unknown configuration.
    original_effective = {**{key:DEFAULTS.get(key,'') for key in KEYS},**env,
                          **{key:str(value) for key,value in saved.items() if key in KEYS}}
    changes = {'DRY_RUN':'false','MAX_ACTIONS_PER_RUN':'1', **{key:'false' for key in DISABLED}}
    saved = {**saved, **changes}
    env.update(changes, AUDITOR_STATE_BACKEND='sqlite', READ_ONLY_API_SERVICE='false')
    effective = {**{key: DEFAULTS.get(key, '') for key in KEYS}, **env,
                 **{key: str(value) for key, value in saved.items() if key in KEYS}}
    policy, _, _, _ = _policy(effective)
    _media(policy, control_identity)
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
        _write_private(log_fd, 'retained-preview-config.json', payloads['saved-config.json'])
        _boundary('after_request')
        _write_private(log_fd, 'auditor_state.json', payloads['tracking-snapshot.json'])
        _write_private(log_fd, 'auditor_config.json', _encode(saved))
        _boundary('before_binding')
        prepare_release_state(source=logs/'auditor_state.json',control_directory=control/'release',
                              expected_source_sha256=hashlib.sha256(payloads['tracking-snapshot.json']).hexdigest())
        create_live_binding(settings=env)
        _boundary('after_binding')
        validate_live_binding(settings=env,for_execution=True)
        if GuardedSQLiteStateStore(control/'release'/'state.db').load_with_revision() != (state, 0):
            raise RuntimeError('Replacement tracking parity changed')
        if parse_unique_json(_local(log_fd, 'auditor_config.json')[0]) != saved:
            raise RuntimeError('Replacement settings changed')
        if load_backup_payloads(**selected) != payloads:
            raise RuntimeError('Selected backup changed during preparation')
        for path, identity in ((logs, logs_identity), (control, control_identity)):
            reopened = _private_root(path, identity); os.close(reopened)
        _write_private(log_fd, 'runtime.env', ''.join(key+'='+value+'\n' for key,value in sorted(env.items())).encode())
        report = {'schema_version': 1, 'status': 'live_candidate_binding_prepared_not_started',
            'source_revision': revision, 'candidate_image_id': image_id,
            'backup_fingerprint': backup_fingerprint, 'tracking_preserved': True,
            'settings_preserved_except_canary_controls': True, 'changed_setting_keys': sorted(key for key,value in changes.items() if original_effective.get(key)!=value),
            'initial_maximum_actions':1, 'permanent_deletion_authorized':False, 'snapshot_revision': 0,
            'service_changes_performed': False, 'media_actions_authorized': False,
            'update_authorized': False, 'automatic_restoration': False,
            'backup_freshness_verified': False}
        _boundary('before_completion')
        validate_live_binding(settings=env,for_execution=True)
        if (GuardedSQLiteStateStore(control/'release'/'state.db').load_with_revision() != (state,0)
                or _local(log_fd,'auditor_state.json')[0] != payloads['tracking-snapshot.json']
                or parse_unique_json(_local(log_fd,'auditor_config.json')[0]) != saved
                or _local(log_fd,'retained-preview-config.json')[0] != payloads['saved-config.json']
                or _local(log_fd,'runtime.env')[0] != ''.join(key+'='+value+'\n' for key,value in sorted(env.items())).encode()
                or load_backup_payloads(**selected) != payloads):
            raise RuntimeError('Live preparation changed before completion')
        for path,identity in ((logs,logs_identity),(control,control_identity)):
            reopened=_private_root(path,identity);os.close(reopened)
        _write_private(log_fd, COMPLETE, _encode(report))
        return report


def main():
    import argparse,sys
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    for key in ('image-id','backup','backup-identity','fingerprint','logs','logs-identity','control','control-identity'):
        parser.add_argument('--'+key,required=True)
    args=parser.parse_args()
    def identity(raw):
        if not re.fullmatch(r'[0-9]{1,20}:[0-9]{1,20}',raw):raise ValueError('Known directory identity required')
        return tuple(map(int,raw.split(':')))
    try:
        raw=sys.stdin.buffer.read(4*1024*1024+1)
        if len(raw)>4*1024*1024:raise ValueError('Bounded image metadata required')
        images=parse_unique_json(raw)
        if (not isinstance(images,list) or len(images)!=1 or not isinstance(images[0],dict)
                or not re.fullmatch(r'sha256:[0-9a-f]{64}',args.image_id) or images[0].get('Id')!=args.image_id):
            raise ValueError('One exact selected image required')
        result=prepare_live_candidate(backup=args.backup,backup_identity=identity(args.backup_identity),
            backup_fingerprint=args.fingerprint,logs=args.logs,logs_identity=identity(args.logs_identity),
            control=args.control,control_identity=identity(args.control_identity),candidate_image=images[0])
    except Exception:
        print(json.dumps({'status':'live_preparation_blocked','partial_files_retained':True,
              'service_changes_performed':False,'media_actions_authorized':False}))
        return 2
    print(json.dumps(result,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
