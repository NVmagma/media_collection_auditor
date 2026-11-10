"""Create private backups and test a separate restore copy without activating it."""
from contextlib import contextmanager
from datetime import datetime,timezone
import hashlib,os,re,secrets,stat
from pathlib import Path
from app.json_backup import create_backup,inspect_backup,FILES,_write
from app.json_validation import parse_unique_json
from app.private_files import _local,_encode
from app.filesystem_paths import _open_directory

LEAF='.auditor-backups'
MARKER=b'media-auditor-private-backups-v1\n'
LIMIT=100
MAX_BYTES=34*1024*1024


def _private(info,directory=False):
    if ((not stat.S_ISDIR(info.st_mode) if directory else not stat.S_ISREG(info.st_mode))
            or info.st_uid!=os.geteuid() or info.st_mode & 0o077 or (not directory and info.st_nlink!=1)):
        raise RuntimeError('Private owned backup files required')


def _read(fd,name):
    raw,info=_local(fd,name);_private(info)
    return raw


@contextmanager
def root(config_file,*,create=False):
    parent=Path(config_file).parent;path=parent/LEAF
    parent_fd=_open_directory(str(parent))
    try:
        if create:
            try:
                os.mkdir(LEAF,0o700,dir_fd=parent_fd)
                new_fd=os.open(LEAF,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent_fd)
                try:_write(new_fd,'.version',MARKER)
                finally:os.close(new_fd)
                os.fsync(parent_fd)
            except FileExistsError:pass
        fd=os.open(LEAF,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent_fd)
        try:
            held=os.fstat(fd);_private(held,True)
            if _read(fd,'.version')!=MARKER:raise RuntimeError('Unknown backup directory')
            def verify():
                current=_open_directory(str(path))
                try:
                    now=os.fstat(current);_private(now,True)
                    if (now.st_dev,now.st_ino)!=(held.st_dev,held.st_ino):raise RuntimeError('Backup directory changed')
                    if _read(current,'.version')!=MARKER:raise RuntimeError('Backup directory changed')
                finally:os.close(current)
            verify();yield path,fd,verify;verify()
        finally:os.close(fd)
    finally:os.close(parent_fd)


def _ids(fd):
    names=os.listdir(fd)
    if len(names)>LIMIT+3:raise RuntimeError('Backup inventory bound exceeded')
    ids=[name for name in names if re.fullmatch('[0-9a-f]{32}',name)]
    if len(ids)>LIMIT:raise RuntimeError('Backup inventory bound exceeded')
    return ids


def _packet(path,fd,identifier):
    if not isinstance(identifier,str) or re.fullmatch('[0-9a-f]{32}',identifier) is None:
        raise ValueError('Known backup identifier required')
    child=os.open(identifier,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
    try:
        info=os.fstat(child);_private(info,True)
        reference=parse_unique_json(_read(child,'browser-selection.json'))
        if (not isinstance(reference,dict) or set(reference)!={'schema_version','directory_identity','backup_fingerprint'}
                or type(reference['schema_version']) is not int or reference['schema_version']!=1
                or not isinstance(reference['directory_identity'],list) or len(reference['directory_identity'])!=2
                or any(type(value) is not int or value<0 for value in reference['directory_identity'])
                or not isinstance(reference['backup_fingerprint'],str)
                or re.fullmatch('[0-9a-f]{64}',reference['backup_fingerprint']) is None
                or reference['directory_identity']!=[info.st_dev,info.st_ino]):
            raise RuntimeError('Backup selection changed')
        arguments=dict(directory=path/identifier,expected_identity=reference['directory_identity'],
            expected_fingerprint=reference['backup_fingerprint'],max_total_bytes=MAX_BYTES)
        report=inspect_backup(**arguments)
        receipt=parse_unique_json(_read(child,'backup-complete.json'))
        payloads={name:_read(child,name) for name in FILES}
        if any(hashlib.sha256(raw).hexdigest()!=receipt['sha256'][name] for name,raw in payloads.items()):
            raise RuntimeError('Backup changed')
        inspect_backup(**arguments)
        return report,payloads,arguments
    finally:os.close(child)


def create(*,state_file,config_file):
    with root(config_file,create=True) as (path,fd,verify):
        if len(_ids(fd))>=LIMIT:raise RuntimeError('Backup limit reached; nothing was deleted')
        identifier=secrets.token_hex(16);verify()
        result=create_backup(state_file=state_file,config_file=config_file,directory=path/identifier)
        verify()
        child=os.open(identifier,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
        try:
            _write(child,'browser-selection.json',_encode(dict(schema_version=1,
                directory_identity=result['directory_identity'],backup_fingerprint=result['backup_fingerprint'])))
        finally:os.close(child)
        _packet(path,fd,identifier)
        return {'status':'backup_created','id':identifier,'active_files_changed':False}


def inventory(*,config_file,page=1):
    if type(page) is not int or not 1<=page<=20:raise ValueError('Bounded backup page required')
    try:
        with root(config_file) as (path,fd,verify):
            ids=_ids(fd)
            ids.sort(key=lambda name:os.stat(name,dir_fd=fd,follow_symlinks=False).st_mtime_ns,reverse=True)
            pages=max(1,(len(ids)+4)//5);page=min(page,pages);rows=[]
            for identifier in ids[(page-1)*5:page*5]:
                try:
                    report,payloads,_=_packet(path,fd,identifier)
                    state=parse_unique_json(payloads['auditor_state.json'])
                    counts={key:len(state[key]) for key in ('first_seen','queued','in_removal','keep_seen','arr_sync_pending')}
                    journal=state.get('json_worker_control')
                    pending=(journal.get('journal') is not None) if isinstance(journal,dict) and 'journal' in journal else None
                    rows.append(dict(id=identifier,status='verified',captured=report['captured_at'],counts=counts,pending=pending))
                except Exception:rows.append(dict(id=identifier,status='unavailable',captured=None,counts=None))
            verify()
            return dict(items=rows,page=page,pages=pages,total=len(ids))
    except FileNotFoundError:
        # Only a missing backup root means no browser backups have been created.
        if not os.path.lexists(Path(config_file).parent/LEAF):
            parent=_open_directory(str(Path(config_file).parent));os.close(parent)
            return dict(items=[],page=1,pages=1,total=0)
        raise


def verify_backup(*,config_file,identifier):
    with root(config_file) as (path,fd,verify):
        report,_,_=_packet(path,fd,identifier);verify()
        return {'status':'backup_verified','id':identifier,'captured':report['captured_at'],'active_files_changed':False}


def test_restore(*,config_file,identifier):
    """Restore into a new test location. Never load or overwrite active files."""
    with root(config_file) as (path,fd,verify):
        _,payloads,arguments=_packet(path,fd,identifier)
        try:os.mkdir('.restore-tests',0o700,dir_fd=fd);os.fsync(fd)
        except FileExistsError:pass
        tests=os.open('.restore-tests',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
        try:
            _private(os.fstat(tests),True)
            if len(os.listdir(tests))>=LIMIT:raise RuntimeError('Restore-test limit reached')
            test_id=secrets.token_hex(16);os.mkdir(test_id,0o700,dir_fd=tests);os.fsync(tests)
            destination=os.open(test_id,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=tests)
            try:
                for name,raw in payloads.items():_write(destination,name,raw)
                if any(_read(destination,name)!=raw for name,raw in payloads.items()):raise RuntimeError('Restore-copy mismatch')
                inspect_backup(**arguments);verify()
                reopened=_open_directory(str(path/'.restore-tests'/test_id))
                try:
                    if (os.fstat(reopened).st_dev,os.fstat(reopened).st_ino)!=(os.fstat(destination).st_dev,os.fstat(destination).st_ino):
                        raise RuntimeError('Restore-test directory changed')
                finally:os.close(reopened)
                _write(destination,'restore-test-complete.json',_encode(dict(schema_version=1,
                    source_id=identifier,test_id=test_id,completed_at=datetime.now(timezone.utc).isoformat(),
                    sha256={name:hashlib.sha256(raw).hexdigest() for name,raw in payloads.items()},
                    worker_started=False,active_restore_performed=False)))
            finally:os.close(destination)
        finally:os.close(tests)
        return {'status':'restore_copy_verified','id':identifier,'test_id':test_id,'active_files_changed':False}
