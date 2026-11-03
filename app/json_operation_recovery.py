"""Explicit GET-only acknowledgment for a verified pending JSON Arr sync.

No remote writes or move replay. Two fresh exact readbacks and unchanged local
media/tracking are required again when applying the selected review fingerprint.
"""
from contextlib import ExitStack
from dataclasses import asdict
import hashlib
import json
import os
import re
import stat

from app.arr_import_service import media_fingerprint
from app.json_move_execution import MoveRequest, TRANSITIONS
from app.json_scan_control import KEY, _control
from app.sqlite_arr_catalog import canonical_arr_record_path
from app.sqlite_lifecycle_checkpoint_plan import CLOCKS
from app.sqlite_scheduled_paths import _canonical, _open_directory
from app.sqlite_title_identity import validate_title_folder


def _inspect(session, read_record):
    session.verify()
    journal = _control(session.state)['journal']
    if not isinstance(journal,dict) or journal['kind'] != 'arr_sync':
        raise RuntimeError('Pending Arr synchronization required')
    details = journal['details']
    if set(details) != {'request','media_key','title_identity','media_fingerprint','media_files','destination_since'}:
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
    clocks = [section for section in CLOCKS.values() if key in session.state[section]]
    if clocks != [CLOCKS[request.destination_stage]] or session.state[clocks[0]][key] != details['destination_since']:
        raise RuntimeError('Moved tracking clock changed')
    before = json.dumps(session.state,sort_keys=True,allow_nan=False).encode()
    with ExitStack() as stack:
        roots=[]
        for path in (request.source_root,request.destination_root):
            fd=_open_directory(path); stack.callback(os.close,fd)
            info=os.fstat(fd); roots.append((fd,path,[info.st_dev,info.st_ino]))
        title_fd=os.open(request.title,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=roots[1][0])
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
            info=os.stat(request.title,dir_fd=roots[1][0],follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode) or [info.st_dev,info.st_ino] != details['title_identity']:
                raise RuntimeError('Moved title replaced')
            try: os.stat(request.title,dir_fd=roots[0][0],follow_symlinks=False)
            except FileNotFoundError: pass
            else: raise RuntimeError('Title source reappeared')
            if media_fingerprint(title_fd) != (details['media_fingerprint'],details['media_files']):
                raise RuntimeError('Moved content changed')
        verify()
        for _ in range(2):
            observed=read_record(request)
            if (not isinstance(observed,dict) or type(observed.get('id')) is not int
                    or observed['id'] != request.title_id
                    or canonical_arr_record_path(observed.get('path')) != request.arr_destination_root+'/'+request.title
                    or type(observed.get('monitored')) is not bool or observed['monitored'] != request.monitored):
                raise RuntimeError('Remote synchronization outcome not verified')
            verify()
        fingerprint=hashlib.sha256(before+json.dumps(session._identity).encode()).hexdigest()
        return fingerprint


def review_pending_sync(store, *, read_record):
    with store.session() as session:
        fingerprint=_inspect(session,read_record)
    return {'status':'pending_sync_matches','review_fingerprint':fingerprint,
        'remote_readbacks':2,'media_actions_performed':False,'arr_updates_sent':0,
        'intent_modified':False,'read_only':True}


def acknowledge_pending_sync(store, *, read_record, expected_fingerprint):
    if not isinstance(expected_fingerprint,str) or re.fullmatch('[0-9a-f]{64}',expected_fingerprint) is None:
        raise ValueError('Exact reviewed synchronization required')
    with store.session() as session:
        fingerprint=_inspect(session,read_record)
        if fingerprint != expected_fingerprint: raise RuntimeError('Reviewed operation changed')
        session.state[KEY]['journal']=None
        session.checkpoint()
    return {'status':'pending_sync_acknowledged','remote_readbacks':2,'arr_updates_sent':0,
        'media_actions_performed':False,'tracking_clocks_preserved':True,'scan_claims_modified':False,
        'automatic_replay':False,'historical_completion_recorded':False}
