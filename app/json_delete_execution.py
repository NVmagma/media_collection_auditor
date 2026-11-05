"""Removal-only Arr deletion, durable intent, and GET-only lost-ack recovery.

No unlink/rmtree, retries, automatic reconciliation or direct filesystem fallback.
"""
from contextlib import ExitStack
from dataclasses import dataclass, asdict
from datetime import datetime
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import os
import stat

from app.arr_catalog import canonical_arr_record_path
from app.arr_import_service import media_fingerprint
from app.mount_identity import read_fd_mount_id
from time import monotonic, sleep
from app.content_observation import observe_scheduled_content
from app.deletion_policy import protected
from app.filesystem_paths import _canonical, _open_directory
from app.json_scan_control import KEY, _control
from app.lifecycle_stages import CLOCKS
from app.title_identity import validate_title_folder


@dataclass(frozen=True)
class DeleteRequest:
    library: str
    title: str
    source_since: str
    threshold_days: int
    roots: dict
    service: str
    title_id: int
    arr_source_path: str
    arr_base_url: str


def _validate(req):
    if (not isinstance(req,DeleteRequest) or req.library not in ('Movies','TV')
            or req.service != ('radarr' if req.library=='Movies' else 'sonarr')
            or type(req.title_id) is not int or req.title_id <= 0
            or type(req.threshold_days) is not int or req.threshold_days < 1
            or not isinstance(req.roots,dict) or set(req.roots)!=set(CLOCKS)):
        raise ValueError('Exact Removal deletion request required')
    from app.arr_catalog import ArrCatalogGET
    ArrCatalogGET(service=req.service,base_url=req.arr_base_url,token='validation-only')
    validate_title_folder(req.title)
    if req.title.startswith('.'): raise ValueError('Media title required')
    paths=[Path(_canonical(value)) for value in req.roots.values()]
    if any(p==Path('/') or p==q or p in q.parents or q in p.parents
           for i,p in enumerate(paths) for q in paths[i+1:]): raise ValueError('Disjoint stage roots required')
    if any(p==Path('/') for p in paths): raise ValueError('Dedicated stage roots required')
    if canonical_arr_record_path(req.arr_source_path)!=req.roots['Removal']+'/'+req.title:
        raise ValueError('Deletion requires identical local and Arr Removal paths; aliases are not approved')
    return ('TV/' if req.library=='TV' else '')+req.title


def _record_matches(req,record):
    return (isinstance(record,dict) and type(record.get('id')) is int and record['id']==req.title_id
        and canonical_arr_record_path(record.get('path'))==req.arr_source_path
        and record.get('monitored') is False)


def deletion_fingerprint(fd):
    # Include metadata/sidecars as well as video, reject nested mounts and hardlinks.
    media_fingerprint(fd)
    root=os.fstat(fd); mount=read_fd_mount_id(fd); rows=[]; started=monotonic()
    for base,dirs,files,directory in os.fwalk('.',dir_fd=fd,follow_symlinks=False):
        if len(Path(base).parts)>16 or read_fd_mount_id(directory)!=mount:
            raise RuntimeError('Deletion inventory crosses a mount or depth bound')
        for name in sorted(dirs+files):
            info=os.stat(name,dir_fd=directory,follow_symlinks=False)
            if (info.st_dev!=root.st_dev or stat.S_ISLNK(info.st_mode)
                    or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode))
                    or stat.S_ISREG(info.st_mode) and info.st_nlink!=1):
                raise RuntimeError('Unsafe deletion inventory')
            rows.append([base,name,info.st_dev,info.st_ino,info.st_mode,info.st_size,info.st_mtime_ns,info.st_ctime_ns])
            if len(rows)>20000 or monotonic()-started>10: raise RuntimeError('Deletion inventory exceeds bounds')
    return hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest(),len(rows)


class DeletionPreflightBlocked(RuntimeError):
    def __init__(self,reason):
        super().__init__(reason)
        self.reason=reason


class DeletionIncomplete(RuntimeError):
    pass


class HeldTitle:
    def __init__(self,session,req): self.session,self.req=session,req
    def __enter__(self):
        self.stack=ExitStack()
        try:
            self.roots={}
            for stage,path in self.req.roots.items():
                p=Path(path)
                if p==self.session._path or p in self.session._path.parents or self.session._path in p.parents:
                    raise ValueError('Media must be separate from tracking')
                fd=_open_directory(path); self.stack.callback(os.close,fd)
                info=os.fstat(fd); self.roots[stage]=(fd,path,(info.st_dev,info.st_ino))
            if len({x[2] for x in self.roots.values()})!=4: raise RuntimeError('Aliased media roots')
            return self
        except BaseException:
            self.stack.close(); raise
    def __exit__(self,*args): self.stack.close()
    def verify(self,*,absent=False,identity=None,fingerprint=None):
        self.session.verify()
        for stage,(fd,path,expected) in self.roots.items():
            reopened=_open_directory(path)
            try:
                info=os.fstat(reopened)
                if (info.st_dev,info.st_ino)!=expected: raise RuntimeError('Stage root changed')
            finally:os.close(reopened)
            try: info=os.stat(self.req.title,dir_fd=fd,follow_symlinks=False)
            except FileNotFoundError:
                if not absent and stage=='Removal': raise RuntimeError('Removal title missing')
                continue
            if stage!='Removal': raise RuntimeError('Title location not unique')
            if absent: raise DeletionIncomplete('Arr file removal has not finished')
            if not stat.S_ISDIR(info.st_mode) or identity and [info.st_dev,info.st_ino]!=identity:
                raise RuntimeError('Removal title replaced')
            title_fd=os.open(self.req.title,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
            try:
                observed=deletion_fingerprint(title_fd)
                if fingerprint and observed!=tuple(fingerprint): raise RuntimeError('Removal contents changed')
            finally:os.close(title_fd)
            self.identity=[info.st_dev,info.st_ino]; self.fingerprint=observed


def execute_delete(attempt,*,request,now,fetch_protection,read_record,send_delete,read_absence,authorize,timezone_info=None):
    key=_validate(request); session=attempt.session; attempt._active()
    if not isinstance(now,datetime) or now.tzinfo is not None: raise ValueError('Local deletion time required')
    since=datetime.fromisoformat(request.source_since)
    if since.tzinfo is not None or since>now or (now-since).days<request.threshold_days:
        raise RuntimeError('Removal waiting period incomplete')
    if [s for s in CLOCKS.values() if key in session.state[s]]!=['in_removal'] or session.state['in_removal'][key]!=request.source_since:
        raise RuntimeError('Removal clock changed')
    if attempt._move_counts.get(request.library,0)>=5 or getattr(attempt,'_delete_counts',{}).get(request.library,0)>=1:
        raise RuntimeError('Deletion action limit reached')
    authorize()
    with HeldTitle(session,request) as held:
        held.verify()
        identity,fingerprint=held.identity,held.fingerprint
        # New content never inherits an old removal date.
        newest=observe_scheduled_content(title_path=request.roots['Removal']+'/'+request.title,
            now=now,timezone_info=timezone_info)
        if newest is not None and newest>since: raise DeletionPreflightBlocked('removal_content_changed')
        try: retained=protected(fetch_protection(request))
        except RuntimeError: raise DeletionPreflightBlocked('deletion_protection_unavailable') from None
        if retained: raise DeletionPreflightBlocked('deletion_protected')
        if not _record_matches(request,read_record(request)): raise DeletionPreflightBlocked('deletion_arr_changed')
        authorize(); held.verify(identity=identity,fingerprint=fingerprint)
        details=dict(request=asdict(request),media_key=key,title_identity=identity,
            media_fingerprint=list(fingerprint),dispatch_attempts=0,
            stage_identities={stage:list(row[2]) for stage,row in held.roots.items()})
        identifier=attempt.record_intent(kind='arr_delete',library=request.library,title=request.title,details=details)
        # Any interruption beyond here retains the intent, including before dispatch.
        authorize(); held.verify(identity=identity,fingerprint=fingerprint)
        if protected(fetch_protection(request)): raise RuntimeError('Jellyfin protection changed before deletion')
        if not _record_matches(request,read_record(request)): raise RuntimeError('Arr record changed before deletion')
        authorize(); held.verify(identity=identity,fingerprint=fingerprint)
        session.state[KEY]['journal']['details']['dispatch_attempts']=1
        session.checkpoint()
        authorize(); held.verify(identity=identity,fingerprint=fingerprint)
        attempt._move_counts[request.library]=attempt._move_counts.get(request.library,0)+1
        attempt._delete_counts=getattr(attempt,'_delete_counts',{})
        attempt._delete_counts[request.library]=attempt._delete_counts.get(request.library,0)+1
        send_delete(request)
        # Arr processes folder removal asynchronously. Poll only GET/observations,
        # never repeat DELETE, and require two complete absence observations.
        deadline=monotonic()+30; confirmed=0
        while confirmed<2:
            remote_absent=read_absence(request) is True
            try:
                held.verify(absent=True); local_absent=True
            except DeletionIncomplete:
                local_absent=False
            confirmed=confirmed+1 if remote_absent and local_absent else 0
            if confirmed==2: break
            if monotonic()>=deadline: raise RuntimeError('Deletion outcome remains pending; review required')
            sleep(0.1)
        # One atomic save removes only the selected clock and clears its intent.
        session.state['in_removal'].pop(key)
        attempt.finish_operation(identifier=identifier,verify_outcome=lambda journal:
            journal['kind']=='arr_delete' and held.verify(absent=True) is None)
        return {'status':'arr_deletion_verified','library':request.library,'media_key':key,
            'title':request.title,'permanent_deletion_requested':True,'reclaimed_bytes_verified':False}


def _review(session,read_absence,read_record=None):
    journal=_control(session.state)['journal']
    if not journal or journal['kind']!='arr_delete': raise RuntimeError('Pending deletion required')
    details=journal['details']; req=DeleteRequest(**details['request']); key=_validate(req)
    if (journal['library']!=req.library or journal['title']!=req.title or details['media_key']!=key
            or type(details['dispatch_attempts']) is not int or details['dispatch_attempts'] not in (0,1) or session.state['in_removal'].get(key)!=req.source_since
            or [s for s in CLOCKS.values() if key in session.state[s]]!=['in_removal']):
        raise RuntimeError('Deletion journal changed')
    before=deepcopy(session.state)
    with HeldTitle(session,req) as held:
        if {s:list(x[2]) for s,x in held.roots.items()}!=details['stage_identities']:
            raise RuntimeError('Deletion stage identity changed')
        outcomes=[]
        for _ in range(2):
            absent=read_absence(req)
            if absent is True:
                held.verify(absent=True); outcomes.append('absent')
            elif absent is False and details['dispatch_attempts']==0 and read_record is not None and _record_matches(req,read_record(req)):
                held.verify(identity=details['title_identity'],fingerprint=details['media_fingerprint'])
                outcomes.append('unchanged')
            else: raise RuntimeError('Deletion outcome not verified; no retry')
        if outcomes[0]!=outcomes[1]: raise RuntimeError('Deletion outcome changed')
        if session.state!=before: raise RuntimeError('Tracking changed during review')
        fingerprint=hashlib.sha256(json.dumps([before,session._identity],sort_keys=True).encode()).hexdigest()
        return fingerprint,key,outcomes[0]


def review_pending_delete(store,*,read_absence,read_record=None):
    with store.session() as session: fingerprint,_,outcome=_review(session,read_absence,read_record)
    return dict(status='deletion_absence_verified' if outcome=='absent' else 'deletion_not_performed',
        required_action='acknowledge_delete' if outcome=='absent' else 'cancel_unperformed_delete',
        review_fingerprint=fingerprint,remote_readbacks=2,media_actions_performed=False,arr_updates_sent=0)


def acknowledge_pending_delete(store,*,read_absence,expected_fingerprint,read_record=None,expected_outcome='absent'):
    with store.session() as session:
        fingerprint,key,outcome=_review(session,read_absence,read_record)
        if outcome!=expected_outcome: raise RuntimeError('Reviewed deletion outcome changed')
        if fingerprint!=expected_fingerprint: raise RuntimeError('Deletion review changed')
        if outcome=='absent': session.state['in_removal'].pop(key)
        session.state[KEY]['journal']=None
        session.checkpoint()
    return dict(status='observed_deletion_recorded' if outcome=='absent' else 'unperformed_deletion_canceled',media_actions_performed=False,arr_updates_sent=0,automatic_retry=False)
