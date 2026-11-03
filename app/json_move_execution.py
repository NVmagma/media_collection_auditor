"""Isolated journaled move executor; not wired to production or a web route.

Trusted adapters must provide fresh protection and exact Arr preflight/readback.
No deletion, copy fallback, implicit retry or recovery is performed here.
"""
from contextlib import ExitStack
from dataclasses import dataclass, asdict
from datetime import datetime
import os
import stat
from pathlib import Path

from app.arr_import_service import media_fingerprint
from app.json_scan_control import KEY
from app.lifecycle_decisions import decide
from app.sqlite_lifecycle_checkpoint_plan import CLOCKS
from app.sqlite_noreplace_rename import rename_directory_noreplace_at
from app.sqlite_scheduled_content import observe_scheduled_content
from app.sqlite_scheduled_paths import _canonical, _open_directory
from app.sqlite_title_identity import validate_title_folder
from app.sqlite_rename_mount_binding import read_fd_mount_id
from app.sqlite_arr_catalog import canonical_arr_record_path

TRANSITIONS = {('Waiting','Holding'),('Waiting','Keep'),('Holding','Removal'),('Holding','Keep')}
ACTIONS = {('Waiting','hold'):'Holding',('Waiting','keep'):'Keep',
           ('Holding','rescue'):'Keep',('Holding','to_removal'):'Removal'}
FIELDS = {'played','favorite','disliked','keep','keep_all','protected'}


@dataclass(frozen=True)
class MoveRequest:
    library: str
    title: str
    source_stage: str
    destination_stage: str
    source_since: str
    threshold_days: int
    source_root: str
    destination_root: str
    service: str
    title_id: int
    arr_source_path: str
    arr_destination_root: str
    monitored: bool


def _identity(info): return [info.st_dev,info.st_ino]


def execute_move(attempt, *, request, now, fetch_protection, arr_preflight, arr_complete,
                 favorites_trigger_keep=True, tv_reset=True, timezone_info=None, per_library_limit=1):
    if (not isinstance(request,MoveRequest) or request.library not in ('Movies','TV')
            or (request.source_stage,request.destination_stage) not in TRANSITIONS
            or request.service != ('radarr' if request.library == 'Movies' else 'sonarr')
            or type(request.title_id) is not int or request.title_id <= 0
            or type(request.monitored) is not bool or type(request.threshold_days) is not int
            or request.threshold_days < 0 or type(favorites_trigger_keep) is not bool
            or type(tv_reset) is not bool or type(per_library_limit) is not int
            or not 1 <= per_library_limit <= 5 or not isinstance(now,datetime) or now.tzinfo is not None
            or now > datetime.now() or not all(callable(fn) for fn in (fetch_protection,arr_preflight,arr_complete))):
        raise ValueError('Explicit safe move request required')
    validate_title_folder(request.title)
    if request.title.startswith('.'): raise ValueError('Media title required')
    for path in (request.source_root,request.destination_root,request.arr_destination_root,request.arr_source_path):
        if _canonical(path) == '/': raise ValueError('Dedicated media paths required')
    if (request.arr_source_path.rsplit('/',1)[-1] != request.title
            or request.arr_source_path == request.arr_destination_root+'/'+request.title):
        raise ValueError('Arr source title mismatch')
    key = ('TV/' if request.library == 'TV' else '')+request.title
    session = attempt.session
    attempt._active()
    if attempt._move_counts.get(request.library,0) >= per_library_limit:
        raise RuntimeError('Library action slots already used')
    source_path,destination_path = Path(request.source_root),Path(request.destination_root)
    if (source_path == destination_path or source_path in destination_path.parents or destination_path in source_path.parents
            or any(root == session._path or root in session._path.parents for root in (source_path,destination_path))):
        raise ValueError('Disjoint media and private state required')
    if session.state[KEY]['journal'] is not None: raise RuntimeError('Operation already pending')
    matches = [section for section in CLOCKS.values() if key in session.state[section]]
    if matches != [CLOCKS[request.source_stage]] or session.state[matches[0]][key] != request.source_since:
        raise RuntimeError('Move clock changed')
    since = datetime.fromisoformat(request.source_since)
    if since.tzinfo is not None or since > now: raise RuntimeError('Invalid source clock')
    with ExitStack() as stack:
        roots = []
        for path in (request.source_root,request.destination_root):
            fd = _open_directory(path); stack.callback(os.close,fd)
            roots.append((fd,path,_identity(os.fstat(fd))))
        source,destination = roots[0][0],roots[1][0]
        if (roots[0][2] == roots[1][2] or roots[0][2][0] != roots[1][2][0]
                or read_fd_mount_id(source) != read_fd_mount_id(destination)):
            raise RuntimeError('Distinct same-device stage roots required')
        title_fd = os.open(request.title,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=source)
        stack.callback(os.close,title_fd)
        identity = _identity(os.fstat(title_fd))
        fingerprint,files = media_fingerprint(title_fd)
        def verify(moved=False):
            session.verify()
            for fd,path,expected in roots:
                reopened = _open_directory(path)
                try:
                    if _identity(os.fstat(reopened)) != expected: raise RuntimeError('Media stage changed')
                finally: os.close(reopened)
            present,absent = (destination,source) if moved else (source,destination)
            info = os.stat(request.title,dir_fd=present,follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode) or _identity(info) != identity:
                raise RuntimeError('Media title identity changed')
            try: os.stat(request.title,dir_fd=absent,follow_symlinks=False)
            except FileNotFoundError: pass
            else: raise RuntimeError('Media destination occupied or ambiguous')
            if media_fingerprint(title_fd) != (fingerprint,files):
                raise RuntimeError('Media contents changed')
        verify()
        signal = fetch_protection(request)
        if (not isinstance(signal,dict) or not FIELDS <= signal.keys()
                or any(type(signal[field]) is not bool for field in FIELDS)
                or signal['protected'] and not signal['keep_all']):
            raise RuntimeError('Fresh protection unavailable')
        action,_ = decide(request.source_stage,(now-since).days,request.threshold_days,
            signal,favorites_trigger_keep)
        if ACTIONS.get((request.source_stage,action)) != request.destination_stage:
            raise RuntimeError('Fresh protection changed decision')
        if request.library == 'TV' and request.source_stage == 'Waiting' and tv_reset:
            latest = observe_scheduled_content(title_path=request.source_root+'/'+request.title,
                now=now,timezone_info=timezone_info)
            if latest is not None and latest > since: raise RuntimeError('TV clock reset required')
        record = arr_preflight(request)
        if (not isinstance(record,dict) or type(record.get('id')) is not int or record['id'] != request.title_id
                or canonical_arr_record_path(record.get('path')) != request.arr_source_path
                or type(record.get('monitored')) is not bool):
            raise RuntimeError('Fresh Arr source unavailable')
        wanted = (record['monitored'] if request.source_stage == 'Waiting' else True) if request.destination_stage == 'Keep' else False
        if request.monitored != wanted: raise RuntimeError('Arr monitoring policy changed')
        verify()
        details = {'request':asdict(request),'media_key':key,'title_identity':identity,
            'media_fingerprint':fingerprint,'media_files':files,'destination_since':now.isoformat(),
            'dispatch_attempts':0}
        identifier = attempt.record_intent(kind='move',library=request.library,title=request.title,details=details)
        attempt._move_counts[request.library]=attempt._move_counts.get(request.library,0)+1
        verify()
        rename_directory_noreplace_at(source,request.title,destination,request.title)
        os.fsync(source); os.fsync(destination)
        verify(moved=True)
        # One atomic checkpoint records both the moved clock and outstanding sync.
        session.state[CLOCKS[request.source_stage]].pop(key)
        session.state[CLOCKS[request.destination_stage]][key] = now.isoformat()
        session.state[KEY]['journal']['kind'] = 'arr_sync'
        session.state[KEY]['journal']['details']['dispatch_attempts'] = 1
        session.checkpoint()
        verify(moved=True)
        sent = arr_complete(request)
        if sent is not True: raise RuntimeError('Arr outcome unresolved')
        # arr_complete must include two fresh independent exact record readbacks.
        attempt.finish_operation(identifier=identifier,verify_outcome=lambda journal:
            journal['kind'] == 'arr_sync' and verify(moved=True) is None)
        return {'status':'move_and_arr_verified','library':request.library,'title':request.title,
            'source_stage':request.source_stage,'destination_stage':request.destination_stage,
            'media_actions_performed':True,'permanent_deletion_performed':False}
