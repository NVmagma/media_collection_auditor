"""Prepare private JSON replacement files from an explicitly verified live backup.

No container, template, media or original-state changes. A later stopped-writer
handoff must revalidate freshness; this receipt alone never authorizes deployment.
"""
from contextlib import ExitStack
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import re

from app.config_store import DEFAULTS,KEYS
from app.json_scan_control import KEY,initialize_control
from app.json_tracking_store import JsonTrackingStore
from app.json_worker_cycle import validate_policy
from app.json_worker_migration import latest_archived_start
from app.sqlite_disposable_restore import _write_private
from app.sqlite_json import parse_unique_json
from app.sqlite_preview_install import _private_root
from app.sqlite_preview_template import RUNTIME_DEFAULTS
from app.sqlite_release_recovery import _encode,_local
from app.sqlite_scheduled_paths import scan_held_directory
from scripts.unraid_live_update_backup import load_backup_payloads

COMPLETE='json-preparation-complete.json'


def _boundary(phase):
    """Disposable failure-injection seam; no production behavior."""


def _environment(current):
    env={}
    for item in current['Config']['Env']:
        key,separator,value=item.partition('=')
        if (not separator or not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*',key) or key in env
                or any(ord(char)<32 or ord(char)==127 for char in value)):
            raise ValueError('Unique lossless runtime environment required')
        env[key]=value
    if any(env.get(key) for key in ('PYTHONHOME','PYTHONSTARTUP','LD_PRELOAD','LD_LIBRARY_PATH')):
        raise ValueError('Custom interpreter environment requires review')
    return {key:value for key,value in env.items() if key not in RUNTIME_DEFAULTS and
        (not key.startswith(('SQLITE_','EXPERIMENTAL_SQLITE_')) or key in ('SQLITE_DAILY_RUN_TIME','SQLITE_DAILY_RUN_TIMEZONE'))}


def prepare(*,backup,backup_identity,backup_fingerprint,root,root_identity,candidate_image,source_revision):
    backup,root=Path(backup),Path(root)
    if (not root.is_absolute() or root.resolve()!=root or backup.resolve()!=backup
            or root==backup or root in backup.parents or backup in root.parents):
        raise ValueError('Disjoint canonical backup and new preparation required')
    config=candidate_image.get('Config',{}); labels=config.get('Labels') or {}
    image_id=candidate_image.get('Id','')
    if (not re.fullmatch('[0-9a-f]{40}',source_revision or '') or not re.fullmatch('sha256:[0-9a-f]{64}',image_id)
            or labels.get('org.opencontainers.image.revision')!=source_revision
            or labels.get('io.media-collection-auditor.worker')!='json-serialized'
            or config.get('Entrypoint')!=['python','-B','-m','app.main'] or config.get('Cmd') not in (None,[])
            or config.get('Volumes') not in (None,{}) or config.get('StopSignal')!='SIGINT'
            or not {'AUDITOR_WORKER_MODE=json_serialized','AUDITOR_STATE_BACKEND=json',
                    'DRY_RUN=true','MAX_ACTIONS_PER_RUN=10'}.issubset(set(config.get('Env',[])))):
        raise ValueError('Exact packaged JSON candidate required')
    selected=dict(directory=backup,expected_identity=backup_identity,expected_fingerprint=backup_fingerprint)
    payloads,receipt=load_backup_payloads(**selected)
    current=parse_unique_json(payloads['current.inspect.json'])
    saved=parse_unique_json(payloads['saved-config.json']); state=parse_unique_json(payloads['tracking-snapshot.json'])
    claims=parse_unique_json(payloads['daily-claims.json'])
    if not isinstance(saved,dict) or KEY in state or 'sqlite_pending_operations' in state or state.get('arr_sync_pending'):
        raise ValueError('Resolved tracking without existing JSON control required')
    env=_environment(current)
    effective={**DEFAULTS,**env,**{key:str(value) for key,value in saved.items() if key in KEYS}}
    validate_policy(effective)
    if effective.get('DRY_RUN','true').strip().lower()!='false': raise ValueError('Reviewed live source settings required')
    zone=effective.get('SQLITE_DAILY_RUN_TIMEZONE') or effective.get('TZ') or 'UTC'
    latest=latest_archived_start(claims,timezone_name=zone)  # Complete claims before any writes.
    proposed=deepcopy(saved); proposed['MAX_ACTIONS_PER_RUN']='10'
    env.update(AUDITOR_STATE_BACKEND='json',AUDITOR_WORKER_MODE='json_serialized',
        STATE_FILE='/app/logs/auditor_state.json',WEB_CONFIG_FILE='/app/logs/auditor_config.json',
        DRY_RUN='false',MAX_ACTIONS_PER_RUN='10')
    for key in ('ALLOW_PERMANENT_DELETE','ALLOW_FILESYSTEM_DELETE','ALLOW_CROSS_FILESYSTEM_MOVES','ENABLE_SEASON_PRUNING'):
        env[key]='false'
    validate_policy({**DEFAULTS,**env,**{key:str(value) for key,value in proposed.items() if key in KEYS}})
    with ExitStack() as stack:
        fd=_private_root(root,root_identity); stack.callback(os.close,fd)
        with scan_held_directory(fd) as entries:
            if next(entries,None) is not None: raise RuntimeError('New empty preparation required; partial attempts cannot replay')
        def verify_root():
            reopened=_private_root(root,root_identity); os.close(reopened)
        _write_private(fd,'json-preparation-request.json',_encode(dict(schema_version=1,
            source_revision=source_revision,candidate_image_id=image_id,backup_fingerprint=backup_fingerprint,
            deployment_authorized=False)))
        _boundary('after_request'); verify_root()
        os.mkdir('logs',0o700,dir_fd=fd)
        logs=root/'logs'; log_info=os.stat('logs',dir_fd=fd,follow_symlinks=False); logs_identity=(log_info.st_dev,log_info.st_ino)
        log_fd=_private_root(logs,logs_identity); stack.callback(os.close,log_fd)
        _write_private(fd,'source-tracking.json',payloads['tracking-snapshot.json'])
        _write_private(fd,'scan-claims-archive.json',payloads['daily-claims.json'])
        _write_private(fd,'source-config.json',payloads['saved-config.json'])
        _write_private(log_fd,'auditor_state.json',payloads['tracking-snapshot.json'])
        _write_private(log_fd,'auditor_config.json',_encode(proposed))
        _boundary('before_control'); verify_root()
        checked_logs=_private_root(logs,logs_identity); os.close(checked_logs)
        store=JsonTrackingStore(logs/'auditor_state.json')
        # Pin the expected log directory before any state checkpoint.
        with store.session() as session:
            info=os.fstat(session._parent)
            if (info.st_dev,info.st_ino)!=logs_identity: raise RuntimeError('Preparation logs replaced')
            verify_root()
            initialize_control(session,previous_started_at=latest)
            actual=deepcopy(session.state); actual.pop(KEY)
            if actual!=state: raise RuntimeError('Tracking parity failed')
        _boundary('after_control'); verify_root()
        _write_private(fd,'runtime.env',''.join(key+'='+value+'\n' for key,value in sorted(env.items())).encode())
        names=('json-preparation-request.json','source-tracking.json','scan-claims-archive.json','source-config.json','runtime.env')
        hashes={name:hashlib.sha256(_local(fd,name)[0]).hexdigest() for name in names}
        hashes.update({'logs/'+name:hashlib.sha256(_local(log_fd,name)[0]).hexdigest()
            for name in ('auditor_state.json','auditor_config.json')})
        if load_backup_payloads(**selected)!=(payloads,receipt): raise RuntimeError('Selected backup changed')
        _boundary('before_completion'); verify_root()
        if load_backup_payloads(**selected)!=(payloads,receipt): raise RuntimeError('Selected backup changed')
        for name,expected in hashes.items():
            parent,filename=(log_fd,name[5:]) if name.startswith('logs/') else (fd,name)
            if hashlib.sha256(_local(parent,filename)[0]).hexdigest()!=expected:
                raise RuntimeError('Prepared file changed before completion')
        reopened=_private_root(logs,logs_identity); os.close(reopened)
        report=dict(schema_version=1,status='json_replacement_prepared_not_started',
            candidate_image_id=image_id,source_revision=source_revision,backup_fingerprint=backup_fingerprint,
            original_container_id=current['Id'],original_image_id=current['Image'],
            original_source_revision=receipt['source_revision'],source_snapshot_revision=receipt['snapshot_revision'],
            tracking_counts={key:len(state.get(key,{})) for key in ('first_seen','queued','in_removal','keep_seen','arr_sync_pending')},
            tracking_preserved=True,unknown_tracking_fields_preserved=True,scan_cooldown_preserved=True,
            archived_attempts=len(claims['entries']),latest_started_at=latest.isoformat(),
            next_live_eligible_at=(latest+timedelta(hours=1)).isoformat(),
            settings_preserved_except_action_limit=True,changed_setting_keys=['MAX_ACTIONS_PER_RUN'] if effective.get('MAX_ACTIONS_PER_RUN')!='10' else [],
            maximum_actions=10,per_library_action_limit=5,permanent_deletion_authorized=False,
            service_changes_performed=False,media_actions_authorized=False,deployment_authorized=False,
            backup_freshness_verified=False,writer_quiescence_verified=False,sha256=hashes)
        _write_private(fd,COMPLETE,_encode(report))
        os.fsync(log_fd); os.fsync(fd)
        return report


def main():
    import argparse,sys
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    parser.add_argument('--backup',required=True); parser.add_argument('--backup-identity',required=True)
    parser.add_argument('--fingerprint',required=True); parser.add_argument('--root',required=True)
    parser.add_argument('--root-identity',required=True); parser.add_argument('--revision',required=True)
    parser.add_argument('--original-container-id',required=True)
    args=parser.parse_args()
    try:
        def identity(value):
            if re.fullmatch('[0-9]+:[0-9]+',value) is None: raise ValueError('Directory identity required')
            return tuple(map(int,value.split(':')))
        raw=sys.stdin.buffer.read(8*1024*1024+1)
        if len(raw)>8*1024*1024: raise ValueError('Bounded image metadata required')
        image=parse_unique_json(raw)
        if not isinstance(image,list) or len(image)!=1: raise ValueError('One cached image required')
        payloads,_=load_backup_payloads(directory=Path(args.backup),expected_identity=identity(args.backup_identity),
            expected_fingerprint=args.fingerprint)
        if parse_unique_json(payloads['current.inspect.json'])['Id']!=args.original_container_id:
            raise RuntimeError('Reviewed original container changed')
        report=prepare(backup=args.backup,backup_identity=identity(args.backup_identity),backup_fingerprint=args.fingerprint,
            root=args.root,root_identity=identity(args.root_identity),candidate_image=image[0],source_revision=args.revision)
        print(json.dumps(report,sort_keys=True)); return 0
    except Exception:
        print(json.dumps(dict(status='json_preparation_blocked',service_changes_performed=False,
            media_actions_authorized=False,partial_files_retained=True,automatic_action='none')))
        return 2


if __name__=='__main__': raise SystemExit(main())
