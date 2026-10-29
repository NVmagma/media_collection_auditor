"""Offline mutable-state binding for a future separate scheduled live image.

This module does not open the production gate, control services, move media,
initialize empty tracking or clear intents. Default/preview images are refused.
"""
from contextlib import ExitStack,closing
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import stat
from app.sqlite_json import parse_unique_json
from app.sqlite_live_policy import validate_initial_live_policy
from app.sqlite_live_integrity import KEY,initialize,verify as verify_integrity
from app.sqlite_preview_activation import _effective,_roots,SETTINGS_MARKER
from app.sqlite_preview_install import _private_root
from app.sqlite_release_preparation import REQUEST,COMPLETE,BACKUP,_identity
from app.sqlite_release_recovery import _prepared_snapshot,_local,_encode
from app.sqlite_disposable_restore import _write_private
from app.sqlite_scheduled_paths import _canonical,_open_directory
from app.sqlite_scheduled_production import _hold_control_database
from app.sqlite_lock import audit_run_lock
from app.sqlite_tracking_view import _candidate_capture
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_rename_mount_binding import read_fd_mount_id

PROFILE='scheduled-live-moves-v1'
BINDING='live-release.json'
PREPARE='live-binding-request.json'


def _revision():
    from app import sqlite_release_profile as build
    if (build.PROFILE!=PROFILE or not isinstance(build.SOURCE_REVISION,str)
            or not re.fullmatch('[0-9a-f]{40}',build.SOURCE_REVISION)):
        raise RuntimeError('Separate immutable live-move profile required')
    return build.SOURCE_REVISION


def _policy(values):
    from app.config_store import KEYS
    config=validate_initial_live_policy(values)
    source=Path(_canonical(values['STATE_FILE']));database=Path(_canonical(values['SQLITE_STATE_FILE']))
    saved=Path(_canonical(values['WEB_CONFIG_FILE']))
    if database.name!='state.db' or source==saved:
        raise RuntimeError('Dedicated live database and distinct source/settings required')
    private=(source,saved,database.parent)
    if any(a==b or a in b.parents or b in a.parents for i,a in enumerate(private) for b in private[i+1:]):
        raise RuntimeError('Disjoint live control and retained inputs required')
    for library in config.libraries:
        for _,value in library.roots:
            media=Path(value)
            if any(media==item or media in item.parents or item in media.parents for item in private):
                raise RuntimeError('Media and private controls must be disjoint')
    keys=set(KEYS)|{'STATE_FILE','SQLITE_STATE_FILE','WEB_CONFIG_FILE','TZ','AUDITOR_STATE_BACKEND','READ_ONLY_API_SERVICE'}
    keys|={f'{prefix}_{stage}_PATH' for prefix in ('RADARR','SONARR') for stage in ('TRANSIENT','HOLDING','KEEP','REMOVAL')}
    digest=hashlib.sha256(_encode({key:values.get(key,'') for key in sorted(keys)})).hexdigest()
    return config,source,database,digest


def _media(config,control_identity):
    roots=_roots(config,control_identity);mounts=set();devices=set()
    for path,device,inode in roots:
        fd=_open_directory(path)
        try:
            info=os.fstat(fd)
            if [info.st_dev,info.st_ino]!=[device,inode]:raise RuntimeError('Live stage changed')
            mounts.add(read_fd_mount_id(fd));devices.add(device)
        finally:os.close(fd)
    if len(mounts)!=1 or len(devices)!=1:raise RuntimeError('Initial live stages require one mount and device')
    return roots


def create_live_binding(*,settings=None):
    revision=_revision();values,config_sha=_effective(settings)
    config,source,database,policy_sha=_policy(values);control=database.parent
    if os.path.lexists(control/'preview-release.json') or os.path.lexists(control/SETTINGS_MARKER):
        raise RuntimeError('New offline live preparation required')
    with _prepared_snapshot(source,control) as (parent,state,state_revision,preparation_id,verify):
        if state_revision!=0:raise RuntimeError('New snapshot preparation required')
        info=os.fstat(parent);control_id=(info.st_dev,info.st_ino)
        db=os.stat('state.db',dir_fd=parent,follow_symlinks=False);db_id=(db.st_dev,db.st_ino)
        inputs={name:hashlib.sha256(_local(parent,name)[0]).hexdigest() for name in (REQUEST,COMPLETE,BACKUP)}
        media=_media(config,control_id);preparation=parse_unique_json(_local(parent,REQUEST)[0]);verify()
    parent=_private_root(control,control_id)
    try:
        with audit_run_lock(source) as verify_source,_hold_control_database(control,database) as verify_control:
            record={'schema_version':1,'profile':PROFILE,'source_revision':revision,'policy_sha256':policy_sha,
                'saved_config_sha256':config_sha,'preparation_id':preparation_id,'prepared_inputs':inputs,
                'control_identity':list(control_id),'database_identity':list(db_id),'initial_revision':0,
                'initial_sha256':hashlib.sha256(_encode(state)).hexdigest(),'media_roots':media,
                'permanent_deletion_authorized':False,'maximum_actions':1}
            def stable():
                verify_source();verify_control()
                current_root=_private_root(control,control_id);os.close(current_root)
                current_db=os.stat('state.db',dir_fd=parent,follow_symlinks=False)
                if (current_db.st_dev,current_db.st_ino)!=db_id:raise RuntimeError('Prepared database replaced')
                source_parent=_open_directory(str(source.parent))
                try:source_raw,source_info=_local(source_parent,source.name)
                finally:os.close(source_parent)
                if (list(_identity(source_info))!=preparation['source_identity']
                        or hashlib.sha256(source_raw).hexdigest()!=preparation['source_sha256']):
                    raise RuntimeError('Retained source changed')
                if {name:hashlib.sha256(_local(parent,name)[0]).hexdigest() for name in inputs}!=inputs:
                    raise RuntimeError('Preparation changed')
                latest,latest_sha=_effective(settings)
                if latest_sha!=config_sha or _policy(latest)[3]!=policy_sha or _media(config,control_id)!=media:
                    raise RuntimeError('Live preparation policy changed')
            stable()
            with _candidate_capture(database) as current:
                if current.state!=state or current.revision!=0:raise RuntimeError('Prepared live state changed')
            _write_private(parent,PREPARE,_encode(record))
            with closing(sqlite3.connect(database.resolve().as_uri()+'?mode=rw',uri=True)) as connection:
                connection.execute('PRAGMA synchronous=FULL');connection.execute('BEGIN IMMEDIATE')
                try:
                    with _candidate_capture(database) as current:
                        if current.state!=state or current.revision!=0:raise RuntimeError('Prepared live state changed')
                    stable();initialize(connection,state=state,revision=0);connection.commit()
                except BaseException:connection.rollback();raise
            stable();_write_private(parent,BINDING,_encode({**record,'request_sha256':hashlib.sha256(_encode(record)).hexdigest()}))
        validate_live_binding(settings=settings,for_execution=True)
        return {'status':'live_binding_prepared_not_activated','production_activation':'disabled',
            'media_actions_authorized':False,'service_changes_performed':False,'state_revision':0}
    finally:os.close(parent)


def validate_live_binding(*,settings=None,for_execution=False):
    revision=_revision()
    if type(for_execution) is not bool:raise ValueError('Known validation purpose required')
    values,config_sha=_effective(settings);config,source,database,policy_sha=_policy(values);control=database.parent
    info=os.stat(control,follow_symlinks=False);identity=(info.st_dev,info.st_ino)
    with ExitStack() as stack:
        parent=_private_root(control,identity);stack.callback(os.close,parent)
        if os.path.lexists(control/SETTINGS_MARKER):raise RuntimeError('Settings recovery required')
        captured={name:_local(parent,name) for name in (BINDING,PREPARE,REQUEST,COMPLETE,BACKUP)}
        binding=parse_unique_json(captured[BINDING][0]);request=parse_unique_json(captured[PREPARE][0])
        preparation=parse_unique_json(captured[REQUEST][0]);receipt=parse_unique_json(captured[COMPLETE][0])
        source_parent=_open_directory(str(source.parent));stack.callback(os.close,source_parent)
        source_parent_info=os.fstat(source_parent)
        original,original_info=_local(source_parent,source.name)
        db=os.stat('state.db',dir_fd=parent,follow_symlinks=False)
        if (not stat.S_ISREG(db.st_mode) or db.st_nlink!=1 or binding!={**request,'request_sha256':hashlib.sha256(captured[PREPARE][0]).hexdigest()}
                or type(binding.get('schema_version')) is not int or binding['schema_version']!=1 or binding.get('profile')!=PROFILE or binding.get('source_revision')!=revision
                or binding.get('policy_sha256')!=policy_sha or binding.get('saved_config_sha256')!=config_sha
                or binding.get('control_identity')!=list(identity) or binding.get('database_identity')!=[db.st_dev,db.st_ino]
                or receipt.get('database_identity')!=[db.st_dev,db.st_ino]
                or binding.get('prepared_inputs')!={name:hashlib.sha256(captured[name][0]).hexdigest() for name in (REQUEST,COMPLETE,BACKUP)}
                or original!=captured[BACKUP][0] or preparation.get('source_identity')!=list(_identity(original_info))
                or binding.get('preparation_id')!=preparation.get('request_id')
                or type(binding.get('initial_revision')) is not int or binding['initial_revision']!=0
                or not isinstance(binding.get('initial_sha256'),str) or not re.fullmatch('[0-9a-f]{64}',binding['initial_sha256'])
                or binding.get('permanent_deletion_authorized') is not False or (type(binding.get('maximum_actions')) is not int or binding['maximum_actions']!=1)
                or binding.get('media_roots')!=_media(config,identity)):
            raise RuntimeError('Live binding mismatch')
        with _candidate_capture(database) as current:
            state=current.state;state_revision=current.revision
            with closing(sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True)) as connection:
                row=connection.execute('SELECT value FROM metadata WHERE key=?',(KEY,)).fetchone()
            if row is None:raise RuntimeError('Live integrity record missing')
            verify_integrity(row[0],state,state_revision)
            if state_revision==0 and hashlib.sha256(_encode(state)).hexdigest()!=binding['initial_sha256']:
                raise RuntimeError('Initial live snapshot changed')
            if for_execution and INTENTS_KEY in state:raise RuntimeError('Unresolved live operation blocks execution')
            latest,latest_sha=_effective(settings)
            if latest_sha!=config_sha or _policy(latest)[3]!=policy_sha or _media(config,identity)!=binding['media_roots']:
                raise RuntimeError('Live policy changed during validation')
            again=_private_root(control,identity);os.close(again)
            reopened=_open_directory(str(source.parent))
            try:
                check=os.fstat(reopened)
                if (check.st_dev,check.st_ino)!=(source_parent_info.st_dev,source_parent_info.st_ino):
                    raise RuntimeError('Retained source parent replaced')
            finally:os.close(reopened)
            if os.path.lexists(control/SETTINGS_MARKER):raise RuntimeError('Settings application began')
            current_source,current_source_info=_local(source_parent,source.name)
            if (_identity(os.stat('state.db',dir_fd=parent,follow_symlinks=False))[:2]!=(db.st_dev,db.st_ino)
                    or current_source!=original or _identity(current_source_info)!=_identity(original_info)):
                raise RuntimeError('Live source or database changed')
            for name,(raw,initial) in captured.items():
                now,now_info=_local(parent,name)
                if now!=raw or _identity(now_info)!=_identity(initial):raise RuntimeError('Live binding input changed')
        return values
