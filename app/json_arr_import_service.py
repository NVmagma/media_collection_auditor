"""Explicit JSON-backed Arr registration of existing folders; no move or search.

The same worker lock covers review and dispatch. One durable import intent
precedes the only POST; uncertain creation can only be reconciled with GETs.
"""
from contextlib import ExitStack,contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import secrets
import stat

from app import arr_import_service as shared
from app.arr_import_transport import ArrImportError
from app.json_scan_control import KEY,_control
from app.json_tracking_store import JsonTrackingStore
from app.json_worker_cycle import stage_paths,validate_policy
from app.json_worker_service import settings_snapshot
from app.json_readonly_scan import _bool
from app.sqlite_scheduled_paths import _open_directory
from app.sqlite_title_identity import validate_title_folder


def values(settings=None):
    captured=deepcopy(settings_snapshot() if settings is None else settings)
    if captured.get('AUDITOR_STATE_BACKEND','json') != 'json': raise ArrImportError('backend_unavailable')
    return validate_policy(captured)[0]


def _pending(session):
    return _control(session.state)['journal']


def _fingerprint(payload,local,settings,profile):
    return shared.digest(dict(payload=payload,local=local,settings=settings,quality_profile=profile))


@contextmanager
def held(selection,settings=None,*,execute=False,allow_pending=False):
    captured=values(settings)
    if execute and _bool(captured,'DRY_RUN','true'): raise ArrImportError('live_import_unavailable')
    if (not isinstance(selection,dict) or set(selection) != {'library','folder','provider_id','quality_profile_id'}):
        raise ArrImportError('selection_invalid')
    library,folder=selection['library'],validate_title_folder(selection['folder'])
    if folder.startswith('.'): raise ArrImportError('unsafe_folder')
    shared.positive(selection['provider_id']); shared.positive(selection['quality_profile_id'])
    config=shared.library_config(captured,library); roots=dict(config.roots)
    local,remote=stage_paths(captured,library)
    store=JsonTrackingStore(captured.get('STATE_FILE','/app/logs/auditor_state.json'))
    paths=list(map(Path,roots.values()))
    if any(a==b or a in b.parents or b in a.parents for i,a in enumerate(paths) for b in paths[i+1:]):
        raise ArrImportError('unsafe_folder')
    if any(a==store.path or a in store.path.parents or store.path in a.parents for a in paths):
        raise ArrImportError('unsafe_folder')
    with store.session() as session,ExitStack() as stack:
        if not allow_pending and (_pending(session) is not None or session.state.get('arr_sync_pending')
                                  or 'sqlite_pending_operations' in session.state):
            raise ArrImportError('pending_operation')
        parents={}; identities=set(); present=[]
        for stage,path in roots.items():
            fd=_open_directory(path); stack.callback(os.close,fd); parents[stage]=fd
            info=os.fstat(fd); identity=(info.st_dev,info.st_ino)
            if identity in identities: raise ArrImportError('unsafe_folder')
            identities.add(identity)
            try: item=os.stat(folder,dir_fd=fd,follow_symlinks=False)
            except FileNotFoundError: continue
            if not stat.S_ISDIR(item.st_mode): raise ArrImportError('unsafe_folder')
            present.append(stage)
        if len(present) != 1: raise ArrImportError('folder_changed')
        stage=present[0]
        title_fd=os.open(folder,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parents[stage])
        stack.callback(os.close,title_fd)
        title_identity=(os.fstat(title_fd).st_dev,os.fstat(title_fd).st_ino)
        media,files=shared.media_fingerprint(title_fd)
        def verify():
            session.verify()
            if json.loads(session._raw) != session.state: raise ArrImportError('tracking_changed')
            if values(settings) != captured: raise ArrImportError('settings_changed')
            locations=[]
            for name,fd in parents.items():
                reopened=_open_directory(roots[name])
                try:
                    current,initial=os.fstat(reopened),os.fstat(fd)
                    if (current.st_dev,current.st_ino) != (initial.st_dev,initial.st_ino):
                        raise ArrImportError('folder_changed')
                finally: os.close(reopened)
                try: info=os.stat(folder,dir_fd=fd,follow_symlinks=False)
                except FileNotFoundError: continue
                locations.append(name)
                if name==stage and (not stat.S_ISDIR(info.st_mode) or (info.st_dev,info.st_ino) != title_identity):
                    raise ArrImportError('folder_changed')
            if locations != [stage] or shared.media_fingerprint(title_fd) != (media,files):
                raise ArrImportError('folder_changed')
        verify()
        observation=dict(path=remote[stage]+'/'+folder,root=remote[stage],stage=stage,
            media_fingerprint=media,media_files=files,title_identity=title_identity,
            state=deepcopy(session.state),state_identity=session._identity)
        yield session,verify,observation,captured
        verify()


def review(*,selection,settings=None):
    with held(selection,settings) as (session,verify,local,captured):
        client=shared.client_for(captured,selection['library'],verify)
        payload,summary,profile=shared.payload_review(client,selection,local)
        verify()
        return {**summary,'review_fingerprint':_fingerprint(payload,local,captured,profile),
            'read_only':True,'execution_authorized':False}


def apply(*,selection,expected_fingerprint,settings=None):
    if not isinstance(expected_fingerprint,str) or re.fullmatch('[0-9a-f]{64}',expected_fingerprint) is None:
        raise ArrImportError('review_required')
    with held(selection,settings,execute=True) as (session,verify,local,captured):
        client=shared.client_for(captured,selection['library'],verify)
        payload,summary,profile=shared.payload_review(client,selection,local)
        if _fingerprint(payload,local,captured,profile) != expected_fingerprint:
            raise ArrImportError('review_changed')
        details={**selection,'path':local['path'],'stage':local['stage'],
            'media_fingerprint':local['media_fingerprint'],'title_identity':list(local['title_identity']),
            'service':client.service}
        intent=dict(id=secrets.token_hex(16),kind='arr_import',library=selection['library'],
            title=selection['folder'],details=details,phase='intent_recorded')
        session.state[KEY]['journal']=deepcopy(intent); session.checkpoint(); verify()
        client.create(payload)
        shared.verify_remote(client,details); verify()
        if _pending(session) != intent: raise ArrImportError('pending_operation_changed')
        session.state[KEY]['journal']=None; session.checkpoint(); verify()
        return dict(status='existing_media_import_verified',state_revision=None,
            verification_scope='arr_record_registration',arr_file_scan_verified=False,
            media_actions_performed=False,download_searches=False,monitoring='off',
            automatic_retry=False,tracking_clocks_preserved=True,daily_claims_modified=False)


def recover(*,expected_fingerprint=None,settings=None):
    captured=values(settings)
    if _bool(captured,'DRY_RUN','true'): raise ArrImportError('live_import_unavailable')
    store=JsonTrackingStore(captured.get('STATE_FILE','/app/logs/auditor_state.json'))
    with store.session() as initial:
        intent=deepcopy(_pending(initial))
    if not isinstance(intent,dict) or intent['kind'] != 'arr_import': raise ArrImportError('no_pending_import')
    details=intent['details']
    if set(details) != {'library','folder','provider_id','quality_profile_id','path','stage',
                       'media_fingerprint','title_identity','service'}:
        raise ArrImportError('pending_operation_changed')
    selection={key:details[key] for key in ('library','folder','provider_id','quality_profile_id')}
    with held(selection,settings,allow_pending=True) as (session,verify,local,current):
        if (_pending(session) != intent or intent['library'] != selection['library'] or intent['title'] != selection['folder']
                or details['path'] != local['path'] or details['stage'] != local['stage']
                or details['media_fingerprint'] != local['media_fingerprint']
                or details['title_identity'] != list(local['title_identity'])):
            raise ArrImportError('pending_operation_changed')
        fingerprint=shared.digest(dict(intent=intent,local=local,settings=current))
        if expected_fingerprint is not None and expected_fingerprint != fingerprint: raise ArrImportError('review_changed')
        client=shared.client_for(current,selection['library'],verify)
        if details['service'] != client.service: raise ArrImportError('pending_operation_changed')
        shared.check_version(client); shared.verify_remote(client,details); verify()
        if expected_fingerprint is None:
            return dict(status='import_outcome_matches',review_fingerprint=fingerprint,read_only=True)
        session.state[KEY]['journal']=None; session.checkpoint(); verify()
        return dict(status='import_intent_reconciled',state_revision=None,arr_create_requests_sent=0,
            media_actions_performed=False,automatic_retry=False)
