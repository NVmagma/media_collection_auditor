"""Review interrupted moves and Arr updates before clearing them.

Reviews only read data. Recording an already completed move never repeats it.
Sending a PUT requires a separate fresh review and a saved, single-use attempt.
"""
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
import re
import stat

from app.arr_import_service import media_fingerprint
from app.json_move_execution import MoveRequest, TRANSITIONS
from app.json_scan_control import KEY, _control
from app.arr_catalog import canonical_arr_record_path
from app.lifecycle_stages import CLOCKS
from app.filesystem_paths import _canonical, _open_directory
from app.title_identity import validate_title_folder


def _inspect(session, read_record, *, kind='arr_sync', durable=False):
    session.verify()
    journal = _control(session.state)['journal']
    if not isinstance(journal,dict) or journal['kind'] != kind:
        raise RuntimeError('Pending Arr synchronization required')
    details = journal['details']
    fields = {'request','media_key','title_identity','media_fingerprint','media_files','destination_since'}
    if set(details) not in (fields,fields | {'dispatch_attempts'}):
        raise RuntimeError('Recognized move synchronization journal required')
    request = MoveRequest(**details['request'])
    validate_title_folder(request.title)
    key = ('TV/' if request.library == 'TV' else '')+request.title
    if (request.library not in ('Movies','TV') or request.title.startswith('.')
            or (request.source_stage,request.destination_stage) not in TRANSITIONS
            or request.service != ('radarr' if request.library == 'Movies' else 'sonarr')
            or type(request.title_id) is not int or request.title_id <= 0 or type(request.monitored) is not bool
            or journal['library'] != request.library or journal['title'] != request.title or details['media_key'] != key
            or not isinstance(details['title_identity'],list) or len(details['title_identity']) != 2
            or any(type(value) is not int or value < 0 for value in details['title_identity'])
            or type(details['media_files']) is not int or details['media_files'] <= 0
            or not isinstance(details['media_fingerprint'],str)
            or re.fullmatch('[0-9a-f]{64}',details['media_fingerprint']) is None):
        raise RuntimeError('Pending operation identity invalid')
    for value in (request.source_root,request.destination_root,request.arr_source_path,request.arr_destination_root):
        if _canonical(value) == '/': raise ValueError('Dedicated media paths required')
    attempts = details.get('dispatch_attempts',0)
    if type(attempts) is not int or not 0 <= attempts <= 1000:
        raise RuntimeError('Dispatch history invalid')
    stamp = datetime.fromisoformat(details['destination_since'])
    if stamp.tzinfo is not None or stamp > datetime.now(): raise RuntimeError('Move observation time invalid')
    clocks = [section for section in CLOCKS.values() if key in session.state[section]]
    clock_stage = request.source_stage if kind == 'move' else request.destination_stage
    expected_stamp = request.source_since if kind == 'move' else details['destination_since']
    if clocks != [CLOCKS[clock_stage]] or session.state[clocks[0]][key] != expected_stamp:
        raise RuntimeError('Moved tracking clock changed')
    before = json.dumps(session.state,sort_keys=True,allow_nan=False).encode()
    with ExitStack() as stack:
        roots=[]
        for path in (request.source_root,request.destination_root):
            fd=_open_directory(path); stack.callback(os.close,fd)
            info=os.fstat(fd); roots.append((fd,path,[info.st_dev,info.st_ino]))
        present=[]
        for index,(fd,_,_) in enumerate(roots):
            try: info=os.stat(request.title,dir_fd=fd,follow_symlinks=False)
            except FileNotFoundError: continue
            present.append((index,info))
        if len(present) != 1: raise RuntimeError('Title location is ambiguous or missing')
        index,info=present[0]
        if not stat.S_ISDIR(info.st_mode) or [info.st_dev,info.st_ino] != details['title_identity']:
            raise RuntimeError('Journaled title replaced')
        physical='destination' if index == 1 else 'source'
        if kind == 'arr_sync' and physical != 'destination': raise RuntimeError('Moved title unavailable')
        title_fd=os.open(request.title,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=roots[index][0])
        stack.callback(os.close,title_fd)
        def verify():
            session.verify()
            if json.dumps(session.state,sort_keys=True,allow_nan=False).encode() != before:
                raise RuntimeError('Tracking changed during acknowledgment')
            for fd,path,identity in roots:
                reopened=_open_directory(path)
                try:
                    current=os.fstat(reopened)
                    if [current.st_dev,current.st_ino] != identity: raise RuntimeError('Media root replaced')
                finally: os.close(reopened)
            info=os.stat(request.title,dir_fd=roots[index][0],follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode) or [info.st_dev,info.st_ino] != details['title_identity']:
                raise RuntimeError('Moved title replaced')
            try: os.stat(request.title,dir_fd=roots[1-index][0],follow_symlinks=False)
            except FileNotFoundError: pass
            else: raise RuntimeError('Title source reappeared')
            if media_fingerprint(title_fd) != (details['media_fingerprint'],details['media_files']):
                raise RuntimeError('Moved content changed')
        verify()
        remote=[]
        for _ in range(2):
            observed=read_record(request)
            if (not isinstance(observed,dict) or type(observed.get('id')) is not int
                    or observed['id'] != request.title_id or type(observed.get('monitored')) is not bool):
                raise RuntimeError('Remote synchronization identity not verified')
            path=canonical_arr_record_path(observed.get('path'))
            outcome=('destination' if path == request.arr_destination_root+'/'+request.title
                and observed['monitored'] == request.monitored else
                'source' if path == request.arr_source_path else None)
            if outcome is None or physical == 'source' and outcome != 'source':
                raise RuntimeError('Remote synchronization outcome not verified')
            remote.append((outcome,observed['monitored']))
            verify()
        if remote[0] != remote[1]: raise RuntimeError('Remote record changed between reads')
        if durable:
            for fd,_,_ in roots: os.fsync(fd)
            verify()
        evidence=json.dumps([session._identity,physical,remote[0]]).encode()
        fingerprint=hashlib.sha256(before+evidence).hexdigest()
        return fingerprint,request,physical,remote[0][0]


def review_pending_sync(store, *, read_record):
    with store.session() as session:
        fingerprint,_,_,outcome=_inspect(session,read_record)
    return {'status':'pending_sync_matches' if outcome == 'destination' else 'pending_sync_not_yet_applied',
        'remote_outcome':outcome,'required_action':'acknowledge' if outcome == 'destination' else 'finish_arr_sync',
        'review_fingerprint':fingerprint,
        'remote_readbacks':2,'media_actions_performed':False,'arr_updates_sent':0,
        'intent_modified':False,'read_only':True}


def acknowledge_pending_sync(store, *, read_record, expected_fingerprint):
    if not isinstance(expected_fingerprint,str) or re.fullmatch('[0-9a-f]{64}',expected_fingerprint) is None:
        raise ValueError('Exact reviewed synchronization required')
    with store.session() as session:
        fingerprint,_,_,outcome=_inspect(session,read_record)
        if outcome != 'destination': raise RuntimeError('Arr update has not been verified')
        if fingerprint != expected_fingerprint: raise RuntimeError('Reviewed operation changed')
        session.state[KEY]['journal']=None
        session.checkpoint()
    return {'status':'pending_sync_acknowledged','remote_readbacks':2,'arr_updates_sent':0,
        'media_actions_performed':False,'tracking_clocks_preserved':True,'scan_claims_modified':False,
        'automatic_replay':False,'historical_completion_recorded':False}


def review_pending_move(store, *, read_record):
    with store.session() as session:
        fingerprint,_,physical,remote=_inspect(session,read_record,kind='move')
    return {'status':'pending_move_observed','physical_location':physical,'remote_outcome':remote,
        'required_action':'record_move' if physical == 'destination' else 'cancel_unperformed_move',
        'review_fingerprint':fingerprint,'remote_readbacks':2,'intent_modified':False,
        'read_only':True,'media_actions_performed':False,'arr_updates_sent':0}


def reconcile_pending_move(store, *, read_record, expected_fingerprint):
    if not isinstance(expected_fingerprint,str) or re.fullmatch('[0-9a-f]{64}',expected_fingerprint) is None:
        raise ValueError('Exact reviewed move required')
    with store.session() as session:
        fingerprint,request,physical,remote=_inspect(session,read_record,kind='move',durable=True)
        if fingerprint != expected_fingerprint: raise RuntimeError('Reviewed move changed')
        journal=session.state[KEY]['journal']; details=journal['details']; key=details['media_key']
        if physical == 'destination':
            session.state[CLOCKS[request.source_stage]].pop(key)
            session.state[CLOCKS[request.destination_stage]][key]=details['destination_since']
            if remote == 'destination': session.state[KEY]['journal']=None
            else: journal['kind']='arr_sync'
            status='observed_move_recorded'
        else:
            session.state[KEY]['journal']=None
            status='unperformed_move_canceled'
        session.checkpoint()
    return {'status':status,'arr_sync_pending':physical == 'destination' and remote == 'source',
        'media_actions_performed':False,'arr_updates_sent':0,'scan_claims_modified':False,
        'automatic_replay':False,'historical_completion_recorded':False}


def finish_pending_sync(store, *, read_record, send_update, expected_fingerprint):
    """Send one reviewed PUT attempt. Restarting the app must not send it again."""
    if (not isinstance(expected_fingerprint,str) or re.fullmatch('[0-9a-f]{64}',expected_fingerprint) is None
            or not callable(send_update)):
        raise ValueError('Exact reviewed sync and trusted update adapter required')
    with store.session() as session:
        fingerprint,request,_,outcome=_inspect(session,read_record)
        if fingerprint != expected_fingerprint or outcome != 'source':
            raise RuntimeError('Reviewed outstanding update changed')
        details=session.state[KEY]['journal']['details']
        attempts=details.get('dispatch_attempts',0)
        if attempts >= 1000: raise RuntimeError('Dispatch limit requires review')
        details['dispatch_attempts']=attempts+1
        session.checkpoint()  # Do not reuse an old review to send another PUT after a failure.
        before=deepcopy(session.state)
        if send_update(request) is not True: raise RuntimeError('Arr outcome remains uncertain')
        session.verify()
        if session.state != before: raise RuntimeError('Tracking changed during update')
        _,_,_,outcome=_inspect(session,read_record)
        if outcome != 'destination': raise RuntimeError('Arr destination not verified')
        session.state[KEY]['journal']=None
        session.checkpoint()
    return {'status':'reviewed_arr_sync_completed','arr_update_attempts':1,'remote_readbacks':2,
        'media_actions_performed':False,'tracking_clocks_preserved':True,
        'scan_claims_modified':False,'automatic_retry':False,'historical_completion_recorded':False}
