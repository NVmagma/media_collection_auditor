"""Atomic recoverable quarantine of verified metadata-only orphan folders.

No unlink, rmtree, Arr updates, overwrite, copy fallback, or automatic recovery.
"""
from contextlib import contextmanager,ExitStack
from copy import deepcopy
from datetime import datetime,timezone
import hashlib,json,os,re,stat,secrets
from pathlib import Path

from app.atomic_rename import rename_directory_noreplace_at
from app.filesystem_paths import _open_directory,_canonical
from app.json_scan_control import KEY,_control
from app.lifecycle_stages import CLOCKS
from app.mount_identity import read_fd_mount_id
from app.orphan_inventory import inspect_fd
from app.orphan_cleanup import STATE_KEY,control,observation,LIMIT,instant,GRACE,OrphanRecheckBlocked

LEAF='.auditor-orphans'
MARKER=b'Media Collection Auditor metadata quarantine v1\n'


def identity(fd):
    info=os.fstat(fd);return [info.st_dev,info.st_ino]


def _marker(fd):
    info=os.fstat(fd)
    if info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=0o700:
        raise RuntimeError('Private quarantine ownership/permissions required')
    child=os.open('.quarantine-version',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
    try:
        before=os.fstat(child)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_size!=len(MARKER) or os.read(child,len(MARKER)+1)!=MARKER:
            raise RuntimeError('Recognized quarantine marker required')
    finally:os.close(child)


def ensure_quarantine(media):
    try:fd=os.open(LEAF,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=media)
    except FileNotFoundError:
        # Publish only a complete new root. Interrupted preparations are retained.
        temporary='.auditor-orphans-prepare-'+secrets.token_hex(16)
        os.mkdir(temporary,0o700,dir_fd=media)
        fd=os.open(temporary,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=media)
        try:
            child=os.open('.quarantine-version',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
            with os.fdopen(child,'wb') as stream:stream.write(MARKER);stream.flush();os.fsync(stream.fileno())
            os.fsync(fd)
            rename_directory_noreplace_at(media,temporary,media,LEAF);os.fsync(media)
        finally:os.close(fd)
        fd=os.open(LEAF,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=media)
    try:_marker(fd)
    except BaseException:os.close(fd);raise
    return fd


@contextmanager
def held_locations(session,*,row,settings,create=False):
    from app.json_worker_cycle import stage_paths
    folder=observation(row)
    roots,_=stage_paths(settings,folder['library'])
    media_path=_canonical(settings.get('MEDIA_PATH','/media'))
    media=Path(media_path);quarantine_path=media_path+'/'+LEAF
    if (folder['source_root']!=roots[folder['stage']] or media==Path('/')
            or media not in Path(folder['source_root']).parents
            or media==session._path or media in session._path.parents
            or any(Path(quarantine_path)==Path(p) or Path(quarantine_path) in Path(p).parents
                or Path(p) in Path(quarantine_path).parents for p in roots.values())):
        raise RuntimeError('Disjoint configured media, quarantine and tracking roots required')
    with ExitStack() as stack:
        media_fd=_open_directory(media_path);stack.callback(os.close,media_fd)
        media_identity=identity(media_fd)
        quarantine=ensure_quarantine(media_fd) if create else _open_directory(quarantine_path)
        stack.callback(os.close,quarantine);_marker(quarantine)
        quarantine_identity=identity(quarantine)
        stages={}
        for stage,path in roots.items():
            fd=_open_directory(path);stack.callback(os.close,fd);stages[stage]=(fd,path,identity(fd))
        source=stages[folder['stage']][0]
        if (identity(source)!=folder['root_identity'] or os.fstat(source).st_dev!=os.fstat(quarantine).st_dev
                or read_fd_mount_id(source)!=read_fd_mount_id(quarantine)
                or len({tuple(item[2]) for item in stages.values()})!=4):
            raise RuntimeError('Original same-mount stage roots required')
        def verify(archive=None,strict=True):
            session.verify();_marker(quarantine)
            for held_fd,path,wanted in [(media_fd,media_path,media_identity),(quarantine,quarantine_path,quarantine_identity),
                    *[(fd,path,wanted) for fd,path,wanted in stages.values()]]:
                reopened=_open_directory(path)
                try:
                    if identity(reopened)!=wanted or read_fd_mount_id(reopened)!=read_fd_mount_id(held_fd):raise RuntimeError('Quarantine or stage root changed')
                finally:os.close(reopened)
            for stage,(fd,_,_) in stages.items():
                try:info=os.stat(folder['title'],dir_fd=fd,follow_symlinks=False)
                except FileNotFoundError:
                    if archive is None and stage==folder['stage']:raise RuntimeError('Orphan source disappeared')
                    continue
                if archive is not None or stage!=folder['stage'] or not stat.S_ISDIR(info.st_mode) or [info.st_dev,info.st_ino]!=folder['identity']:
                    raise RuntimeError('Orphan location changed or is ambiguous')
            parent,name=(quarantine,archive) if archive is not None else (source,folder['title'])
            title_fd=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
            try:
                if identity(title_fd)!=folder['identity']:raise RuntimeError('Quarantined folder replaced')
                if not strict:return
                current=inspect_fd(title_fd)
                if (current['status']!='metadata_only' or current['identity']!=folder['identity']
                        or current['fingerprint']!=folder['fingerprint']):
                    raise RuntimeError('Metadata changed or video appeared; nothing was deleted')
            finally:os.close(title_fd)
        yield {'source':source,'quarantine':quarantine,'verify':verify,
            'quarantine_path':quarantine_path,'media_identity':media_identity,'quarantine_identity':quarantine_identity,
            'stage_identities':{key:value[2] for key,value in stages.items()}}


def execute_quarantine(attempt,*,row,settings,now,fresh_absence,authorize):
    now=instant(now);folder=observation(row);session=attempt.session;attempt._active()
    saved=control(session.state);key=folder['media_key'];observed=saved['observations'].get(key)
    if (not isinstance(observed,dict) or observed['folder']!=folder
            or now-instant(observed['first_observed_at'])<GRACE
            or instant(observed['last_observed_at'])!=now or len(saved['quarantined'])>=LIMIT):
        raise RuntimeError('Fresh stable orphan observations required')
    if attempt._move_counts.get(folder['library'],0)>=5:raise RuntimeError('Library action cap reached')
    clocks={section:session.state[section][key] for section in CLOCKS.values() if key in session.state[section]}
    if clocks and set(clocks)!={CLOCKS[folder['stage']]}:raise RuntimeError('Conflicting orphan tracking clocks')
    authorize()
    if fresh_absence(folder) is not True:raise OrphanRecheckBlocked('Fresh Arr/Jellyfin absence not verified')
    with held_locations(session,row=folder,settings=settings,create=True) as held:
        held['verify']();authorize()
        archive=secrets.token_hex(16)
        details={'folder':folder,'archive':archive,'clocks':clocks,'observed_at':now.isoformat(),
            **{key:held[key] for key in ('quarantine_path','media_identity','quarantine_identity','stage_identities')}}
        identifier=attempt.record_intent(kind='orphan_quarantine',library=folder['library'],title=folder['title'],details=details)
        held['verify']();authorize()
        rename_directory_noreplace_at(held['source'],folder['title'],held['quarantine'],archive)
        os.fsync(held['source']);os.fsync(held['quarantine'])
        held['verify'](archive)
        _complete(session,details)
        attempt.finish_operation(identifier=identifier,verify_outcome=lambda journal:
            journal['kind']=='orphan_quarantine' and held['verify'](archive) is None)
        attempt._move_counts[folder['library']]=attempt._move_counts.get(folder['library'],0)+1
        return dict(status='metadata_quarantined',media_key=key,quarantine_id=archive,media_deleted=False)


def _complete(session,details):
    value=control(session.state);folder=details['folder'];key=folder['media_key']
    if details['archive'] in value['quarantined']:raise RuntimeError('Quarantine receipt already occupied')
    if len(value['quarantined'])>=LIMIT:raise RuntimeError('Quarantine receipt limit reached')
    current={section:session.state[section][key] for section in CLOCKS.values() if key in session.state[section]}
    if current!=details['clocks']:raise RuntimeError('Orphan clocks changed')
    for section in current:session.state[section].pop(key)
    value['observations'].pop(key,None);value['quarantined'][details['archive']]=deepcopy(details)
    session.state[STATE_KEY]=value


def _review(session,settings):
    journal=_control(session.state)['journal']
    if not journal or journal['kind']!='orphan_quarantine':raise RuntimeError('Pending metadata quarantine required')
    details=deepcopy(journal['details']);folder=observation(details['folder'])
    archive=details['archive']
    if (journal['library']!=folder['library'] or journal['title']!=folder['title']
            or re.fullmatch('[0-9a-f]{32}',archive) is None):raise RuntimeError('Exact quarantine journal required')
    before=deepcopy(session.state)
    with held_locations(session,row=folder,settings=settings) as held:
        if details.get('quarantine_path',held['quarantine_path'])!=held['quarantine_path']:raise RuntimeError('Recorded quarantine path changed')
        if any(held[key]!=details[key] for key in ('media_identity','quarantine_identity','stage_identities')):
            raise RuntimeError('Quarantine roots changed')
        try:os.stat(archive,dir_fd=held['quarantine'],follow_symlinks=False);moved=True
        except FileNotFoundError:moved=False
        modified=False
        if moved:
            try:held['verify'](archive)
            except RuntimeError:
                held['verify'](archive,strict=False);modified=True
        else:held['verify'](strict=False)
        if session.state!=before:raise RuntimeError('Tracking changed during quarantine review')
        fingerprint=hashlib.sha256(json.dumps([before,session._identity,moved,modified],sort_keys=True).encode()).hexdigest()
        return fingerprint,details,moved,modified


def review_pending_quarantine(store,*,settings):
    with store.session() as session:fingerprint,_,moved,modified=_review(session,settings)
    return dict(status='modified_quarantine_requires_restore' if modified else 'metadata_quarantine_observed',review_fingerprint=fingerprint,
        required_action='restore_quarantine_source' if modified else 'record_quarantine' if moved else 'cancel_unperformed_quarantine',
        read_only=True,media_actions_performed=False,arr_updates_sent=0)


def reconcile_pending_quarantine(store,*,settings,expected_fingerprint,restore_source=False):
    with store.session() as session:
        fingerprint,details,moved,modified=_review(session,settings)
        if fingerprint!=expected_fingerprint:raise RuntimeError('Quarantine review changed')
        if modified:
            if not restore_source:raise RuntimeError('Explicit restoration to the original empty location is required')
            with held_locations(session,row=details['folder'],settings=settings) as held:
                held['verify'](details['archive'],strict=False)
                rename_directory_noreplace_at(held['quarantine'],details['archive'],held['source'],details['folder']['title'])
                os.fsync(held['quarantine']);os.fsync(held['source']);held['verify'](strict=False)
        elif restore_source:raise RuntimeError('Reviewed restoration no longer matches')
        else:
            with held_locations(session,row=details['folder'],settings=settings) as held:
                if any(held[key]!=details[key] for key in ('media_identity','quarantine_identity','stage_identities')):
                    raise RuntimeError('Quarantine roots changed')
                held['verify'](details['archive'] if moved else None,strict=moved)
                os.fsync(held['source']);os.fsync(held['quarantine'])
                if moved:_complete(session,details)
        session.state[KEY]['journal']=None;session.checkpoint()
    return dict(status='quarantine_restored_to_source' if modified else 'observed_quarantine_recorded' if moved else 'unperformed_quarantine_canceled',
        media_actions_performed=modified,arr_updates_sent=0,automatic_retry=False)


def main():
    """List bounded recorded recovery receipts without raw settings or clocks."""
    import argparse
    from app.json_worker_service import settings_snapshot
    from app.json_tracking_store import JsonTrackingStore
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['list'])
    parser.add_argument('--limit',type=int,default=100)
    args=parser.parse_args()
    if not 1<=args.limit<=1000:parser.error('Choose a limit from 1 through 1000')
    values=settings_snapshot()
    with JsonTrackingStore(values.get('STATE_FILE','/app/logs/auditor_state.json')).session() as session:
        receipts=control(session.state)['quarantined']
        for archive,receipt in list(receipts.items())[-args.limit:]:
            folder=observation(receipt['folder'])
            if re.fullmatch('[0-9a-f]{32}',archive) is None:raise RuntimeError('Quarantine receipt requires review')
            print(json.dumps({'status':'recorded_quarantine_receipt','read_only':True,
                'quarantine_id':archive,'library':folder['library'],'title':folder['title'],
                'original_stage':folder['stage'],'original_path':folder['source_root']+'/'+folder['title'],
                'quarantine_path':receipt.get('quarantine_path')+'/'+archive if isinstance(receipt.get('quarantine_path'),str) else None,
                'current_inventory_verified':False}))
    return 0


if __name__=='__main__':raise SystemExit(main())
