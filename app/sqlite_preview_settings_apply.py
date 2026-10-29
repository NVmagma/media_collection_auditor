"""Single-attempt preview settings application and explicit restoration.

The caller supplies original runtime settings and the reviewed request digest.
Only configuration and its binding change. Tracking, clocks, preparation receipts,
media, services and the process environment are never written by this module.
"""
from contextlib import ExitStack
import hashlib
import os
from pathlib import Path
import re
import stat

from app.config_store import KEYS, DEFAULTS, validate
from app.sqlite_disposable_restore import _write_private
from app.sqlite_json import parse_unique_json
from app.sqlite_preview_activation import (BINDING, SETTINGS_MARKER, _revision,
    _policy, _roots, validate_preview_activation, _validate_bound_preview)
from app.sqlite_preview_settings import PENDING
from app.sqlite_release_recovery import _encode, _local, _prepared_snapshot
from app.sqlite_scheduled_paths import _canonical, _open_directory


ARTIFACTS = ('old-config.json','old-binding.json','new-config.json','new-binding.json','request.json')


def _boundary(phase):
    """Fault-injection seam; no automatic retry or restoration."""


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value):
    if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{64}',value):
        raise ValueError('Exact reviewed settings request digest required')
    return value


def _inode(info):
    return [info.st_dev,info.st_ino]


def _replace(parent,name,old_raw,old_inode,staged,new_raw,new_inode):
    current,info=_local(parent,name)
    raw,staging_info=_local(parent,staged)
    if (current!=old_raw or _inode(info)!=old_inode or raw!=new_raw or _inode(staging_info)!=new_inode):
        raise RuntimeError('Settings file changed before replacement')
    os.replace(staged,name,src_dir_fd=parent,dst_dir_fd=parent)
    os.fsync(parent)
    raw,info=_local(parent,name)
    if raw!=new_raw or _inode(info)!=new_inode:
        raise RuntimeError('Settings replacement acknowledgement uncertain')


def _preview_protocol():
    from types import SimpleNamespace
    def check_revision(value):
        if value!=0:raise RuntimeError('Frozen preview tracking required')
    def validate_values(values,settings,previous):
        if (values.get('DRY_RUN','').lower()!='true' or any(values.get(key,'false').lower()!='false' for key in (
                'ALLOW_FILESYSTEM_DELETE','ALLOW_PERMANENT_DELETE','ALLOW_CROSS_FILESYSTEM_MOVES','ENABLE_SEASON_PRUNING'))):
            raise RuntimeError('Settings application cannot enable media actions')
    return SimpleNamespace(binding=BINDING,revision=_revision,policy=_policy,roots=_roots,
        validate=validate_preview_activation,validate_bound=_validate_bound_preview,
        check_revision=check_revision,validate_values=validate_values)


def _paths(settings,protocol):
    protocol.revision()  # Immutable preview profile; environment cannot enable this code.
    if settings.get('AUDITOR_STATE_BACKEND')!='sqlite':
        raise RuntimeError('SQLite preview runtime required')
    source=Path(_canonical(settings.get('STATE_FILE','/app/logs/auditor_state.json')))
    database=Path(_canonical(settings.get('SQLITE_STATE_FILE','/app/logs/sqlite_worker/state.db')))
    config=Path(_canonical(settings.get('WEB_CONFIG_FILE','/app/logs/auditor_config.json')))
    if database.name!='state.db' or config==source or database.parent in config.parents:
        raise RuntimeError('Separate preview settings and tracking required')
    return source,database,config


def apply_requested_settings(*, settings, request_sha256, _protocol=None):
    protocol=_preview_protocol() if _protocol is None else _protocol
    BINDING,_revision,_policy,_roots=protocol.binding,protocol.revision,protocol.policy,protocol.roots
    validate_preview_activation,_validate_bound_preview=protocol.validate,protocol.validate_bound
    request_sha256=_digest(request_sha256)
    settings=dict(settings)
    source,database,config=_paths(settings,protocol)
    control=database.parent
    with _prepared_snapshot(source,control) as (parent,state,revision,_,verify):
        protocol.check_revision(revision)
        validate_preview_activation(settings=settings)
        with ExitStack() as stack:
            config_fd=_open_directory(str(config.parent));stack.callback(os.close,config_fd)
            root_fd=_open_directory(str(control.parent));stack.callback(os.close,root_fd)
            config_parent=_inode(os.fstat(config_fd)); control_parent=_inode(os.fstat(parent))
            old_config,old_info=_local(config_fd,config.name)
            pending,pending_info=_local(config_fd,PENDING)
            if _sha(pending)!=request_sha256:raise RuntimeError('Settings request changed')
            request=parse_unique_json(pending)
            if (not isinstance(request,dict) or type(request.get('schema_version')) is not int
                    or request['schema_version']!=1 or request.get('base_config_sha256')!=_sha(old_config)
                    or request.get('media_actions_authorized') is not False
                    or not isinstance(request.get('requested_config'),dict)):
                raise RuntimeError('Current settings request required')
            previous=parse_unique_json(old_config); proposed=request['requested_config']
            if {k:v for k,v in proposed.items() if k not in KEYS}!={k:v for k,v in previous.items() if k not in KEYS}:
                raise RuntimeError('Unknown saved settings must be preserved')
            proposed=dict(proposed)
            for key in KEYS & proposed.keys():
                if not isinstance(proposed[key],str):raise ValueError('Text settings values required')
                proposed[key]=validate(key,proposed[key])
            values=dict(settings)
            for key in KEYS:values.setdefault(key,DEFAULTS.get(key,''))
            values.update({key:value for key,value in proposed.items() if key in KEYS})
            protocol.validate_values(values,settings,previous)
            policy,_,_,policy_sha=_policy(values)
            new_config=_encode(proposed)
            old_binding,binding_info=_local(parent,BINDING)
            binding=parse_unique_json(old_binding)
            binding.update(saved_config_sha256=_sha(new_config),policy_sha256=policy_sha,
                media_roots=_roots(policy,_inode(os.fstat(parent))))
            new_binding=_encode(binding)
            def check():
                verify()
                for path,expected in ((config.parent,config_parent),(control,control_parent)):
                    fd=_open_directory(str(path))
                    try:
                        if _inode(os.fstat(fd))!=expected:raise RuntimeError('Settings directory changed')
                    finally:os.close(fd)
                if _local(config_fd,PENDING)[0]!=pending:raise RuntimeError('Settings request changed during application')
            check()
            attempt='settings-apply-'+request_sha256
            os.mkdir(attempt,0o700,dir_fd=root_fd);os.fsync(root_fd)
            tx=os.open(attempt,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=root_fd);stack.callback(os.close,tx)
            artifacts=dict(zip(ARTIFACTS,(old_config,old_binding,new_config,new_binding,pending)))
            for name,raw in artifacts.items():_write_private(tx,name,raw)
            stages={}
            for label,fd,raw in (('config',config_fd,new_config),('binding',parent,new_binding)):
                name='.settings-next-'+request_sha256+'-'+label
                _write_private(fd,name,raw)
                stages[label]={'name':name,'inode':_inode(_local(fd,name)[1])}
            record={'schema_version':1,'source_revision':_revision(),'request_sha256':request_sha256,
                'paths':[str(source),str(database),str(config)],'config_parent':config_parent,'control':control_parent,
                'old_config_inode':_inode(old_info),'old_binding_inode':_inode(binding_info),
                'stages':stages,'artifacts':{name:_sha(raw) for name,raw in artifacts.items()},
                'snapshot_sha256':_sha(_encode(state)),'media_actions_authorized':False}
            _write_private(tx,'plan.json',_encode(record))
            marker=_encode({'schema_version':1,'attempt':attempt,'attempt_inode':_inode(os.fstat(tx)),
                'plan_sha256':_sha(_encode(record))})
            check();validate_preview_activation(settings=settings)
            _write_private(parent,SETTINGS_MARKER,marker)
            _boundary('after_intent')
            check()
            _replace(config_fd,config.name,old_config,_inode(old_info),stages['config']['name'],new_config,stages['config']['inode'])
            _boundary('after_config')
            check()
            _replace(parent,BINDING,old_binding,_inode(binding_info),stages['binding']['name'],new_binding,stages['binding']['inode'])
            _boundary('after_binding')
            check();_validate_bound_preview(settings=settings)
            if _local(parent,SETTINGS_MARKER)[0]!=marker:raise RuntimeError('Settings intent changed')
            _write_private(tx,'complete.json',_encode({'status':'settings_applied','media_actions_authorized':False}))
            _boundary('after_complete')
            # A newer request must never be consumed by this application.
            check();os.unlink(PENDING,dir_fd=config_fd);os.fsync(config_fd)
            os.unlink(SETTINGS_MARKER,dir_fd=parent);os.fsync(parent)
            validate_preview_activation(settings=settings);verify()
            return {'status':'settings_applied','tracking_unchanged':True,'media_actions_authorized':False,
                'restart_required':False,'automatic_restoration':False}


def restore_previous_settings(*,settings,request_sha256, _protocol=None):
    """Explicit, single recovery attempt; never adopt an unknown file version."""
    protocol=_preview_protocol() if _protocol is None else _protocol
    BINDING,_revision=protocol.binding,protocol.revision
    validate_preview_activation,_validate_bound_preview=protocol.validate,protocol.validate_bound
    request_sha256=_digest(request_sha256)
    source,database,config=_paths(settings,protocol);control=database.parent
    with _prepared_snapshot(source,control) as (parent,state,revision,_,verify):
        protocol.check_revision(revision)
        with ExitStack() as stack:
            config_fd=_open_directory(str(config.parent));stack.callback(os.close,config_fd)
            root_fd=_open_directory(str(control.parent));stack.callback(os.close,root_fd)
            marker,_=_local(parent,SETTINGS_MARKER);selected=parse_unique_json(marker)
            attempt='settings-apply-'+request_sha256
            if not isinstance(selected,dict):raise RuntimeError('Settings marker needs review')
            if selected.get('attempt')!=attempt:raise RuntimeError('Different settings attempt selected')
            tx=os.open(attempt,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=root_fd);stack.callback(os.close,tx)
            transaction=os.fstat(tx)
            if (_inode(transaction)!=selected.get('attempt_inode') or transaction.st_uid!=os.geteuid()
                    or stat.S_IMODE(transaction.st_mode)!=0o700):
                raise RuntimeError('Private settings transaction directory changed')
            plan_raw,_=_local(tx,'plan.json');plan=parse_unique_json(plan_raw)
            if not isinstance(plan,dict):raise RuntimeError('Settings plan needs review')
            if (_sha(plan_raw)!=selected.get('plan_sha256') or plan.get('source_revision')!=_revision()
                    or plan.get('paths')!=[str(source),str(database),str(config)]
                    or plan.get('snapshot_sha256')!=_sha(_encode(state))
                    or plan.get('config_parent')!=_inode(os.fstat(config_fd)) or plan.get('control')!=_inode(os.fstat(parent))):
                raise RuntimeError('Settings recovery context changed')
            artifacts={name:_local(tx,name)[0] for name in ARTIFACTS}
            if {name:_sha(raw) for name,raw in artifacts.items()}!=plan['artifacts']:
                raise RuntimeError('Settings recovery records changed')
            try:
                restore_raw,_=_local(tx,'restore-request.json')
                restoration=parse_unique_json(restore_raw)
                if not isinstance(restoration,dict):raise RuntimeError('Restoration plan needs review')
                if (restoration.get('request_sha256')!=request_sha256
                        or restoration.get('plan_sha256')!=_sha(plan_raw)):
                    raise RuntimeError('Different restoration selected')
            except FileNotFoundError:
                restoration=None
            live={}
            for label,fd,name in (('config',config_fd,config.name),('binding',parent,BINDING)):
                raw,info=_local(fd,name)
                known=[('old',plan['old_'+label+'_inode']),('new',plan['stages'][label]['inode'])]
                if restoration is not None:
                    known.append(('old',restoration['stages'][label]['inode']))
                if not any(raw==artifacts[version+'-'+label+'.json'] and _inode(info)==identity for version,identity in known):
                    raise RuntimeError('Unknown settings version requires review')
                live[label]=(raw,_inode(info))
            verify()
            if restoration is None:
                stages={}
                for label,fd in (('config',config_fd),('binding',parent)):
                    staged='.settings-restore-'+request_sha256+'-'+label
                    _write_private(fd,staged,artifacts['old-'+label+'.json'])
                    stages[label]={'name':staged,'inode':_inode(_local(fd,staged)[1])}
                restoration={'request_sha256':request_sha256,'plan_sha256':_sha(plan_raw),
                    'stages':stages,'automatic_restoration':False}
                _write_private(tx,'restore-request.json',_encode(restoration))
            for label,fd,name in (('config',config_fd,config.name),('binding',parent,BINDING)):
                raw=artifacts['old-'+label+'.json']
                if live[label][0]==raw:continue
                stage=restoration['stages'][label]
                if stage['name']!='.settings-restore-'+request_sha256+'-'+label:
                    raise RuntimeError('Unknown restoration staging file')
                _replace(fd,name,*live[label],stage['name'],raw,stage['inode'])
                _boundary('restored_'+label)
            verify();_validate_bound_preview(settings=settings)
            if _local(parent,SETTINGS_MARKER)[0]!=marker:raise RuntimeError('Settings intent changed')
            receipt=_encode({'status':'previous_settings_restored','media_actions_authorized':False})
            try:
                if _local(tx,'restored.json')[0]!=receipt:raise RuntimeError('Restoration receipt changed')
            except FileNotFoundError:
                _write_private(tx,'restored.json',receipt)
            os.unlink(SETTINGS_MARKER,dir_fd=parent);os.fsync(parent)
            validate_preview_activation(settings=settings)
            return {'status':'previous_settings_restored','tracking_unchanged':True,
                'media_actions_authorized':False,'automatic_restoration':False}


def application_status(*,settings):
    """Read-only UI projection; a digest selects a request, never authorizes it."""
    from app.sqlite_preview_settings import _read_regular,pending_request_summary
    try:
        config=Path(_canonical(settings.get('WEB_CONFIG_FILE','/app/logs/auditor_config.json')))
        control=Path(_canonical(settings.get('SQLITE_STATE_FILE','/app/logs/sqlite_worker/state.db'))).parent
        marker=control/SETTINGS_MARKER
        if os.path.lexists(marker):
            value=parse_unique_json(_read_regular(marker))
            match=re.fullmatch('settings-apply-([0-9a-f]{64})',value.get('attempt',''))
            if not match:return {'status':'review_required'}
            return {'status':'recovery_required','request_sha256':match.group(1)}
        summary=pending_request_summary(config_path=config,environment=settings)
        if summary['status']=='none':return {'status':'none'}
        if summary['status']!='requested':return {'status':'review_required'}
        digest=_sha(_read_regular(config.parent/PENDING))
        if os.path.lexists(control.parent/('settings-apply-'+digest)):
            return {'status':'resubmit_required'}
        return {'status':'ready','request_sha256':digest}
    except Exception:
        return {'status':'review_required'}
