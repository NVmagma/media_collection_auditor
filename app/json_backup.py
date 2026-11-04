"""Private JSON tracking/settings snapshots and read-only receipt verification."""
from datetime import datetime,timezone
import hashlib,os,re
from pathlib import Path
from app.json_tracking_store import JsonTrackingStore
from app.json_validation import parse_unique_json
from app.private_files import _local,_encode
from app.filesystem_paths import _open_directory
from app.tracking_schema import validate_snapshot

FILES=('auditor_state.json','saved-config.json')


def _write(fd,name,raw):
    child=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
    with os.fdopen(child,'wb') as stream: stream.write(raw);stream.flush();os.fsync(stream.fileno())
    os.fsync(fd)


def create_backup(*,state_file,config_file,directory):
    root=Path(directory);state=Path(state_file);config=Path(config_file)
    if not root.is_absolute() or root.parent.resolve()!=root.parent or any(root==p or root in p.parents for p in (state,config)):
        raise ValueError('New disjoint private backup directory required')
    with JsonTrackingStore(state).session() as session:
        parent=_open_directory(str(config.parent))
        try: saved,info=_local(parent,config.name)
        finally:os.close(parent)
        if not isinstance(parse_unique_json(saved),dict):raise ValueError('Settings object required')
        os.mkdir(root,0o700);fd=_open_directory(str(root))
        try:
            payloads={'auditor_state.json':session._raw,'saved-config.json':saved}
            for name,raw in payloads.items():_write(fd,name,raw)
            session.verify()
            parent=_open_directory(str(config.parent))
            try:
                if _local(parent,config.name)[0]!=saved:raise RuntimeError('Settings changed during backup')
            finally:os.close(parent)
            receipt=dict(schema_version=1,kind='json_tracking_and_settings',captured_at=datetime.now(timezone.utc).isoformat(),
                sha256={name:hashlib.sha256(raw).hexdigest() for name,raw in payloads.items()},restore_authorized=False)
            raw=_encode(receipt);_write(fd,'backup-complete.json',raw)
            return dict(status='json_backup_created',backup_fingerprint=hashlib.sha256(raw).hexdigest(),
                directory_identity=[root.stat().st_dev,root.stat().st_ino],restore_authorized=False)
        finally:os.close(fd)


def inspect_backup(*,directory,expected_identity,expected_fingerprint,max_total_bytes=16*1024*1024):
    root=Path(directory);fd=_open_directory(str(root))
    try:
        info=os.fstat(fd)
        if (info.st_dev,info.st_ino)!=tuple(expected_identity):raise RuntimeError('Backup directory changed')
        raw=_local(fd,'backup-complete.json')[0]
        if not re.fullmatch('[0-9a-f]{64}',expected_fingerprint) or hashlib.sha256(raw).hexdigest()!=expected_fingerprint:
            raise RuntimeError('Backup receipt changed')
        value=parse_unique_json(raw)
        if value.get('schema_version')!=1 or value.get('kind')!='json_tracking_and_settings' or value.get('restore_authorized') is not False or set(value.get('sha256',{}))!=set(FILES):
            raise RuntimeError('Complete JSON backup receipt required')
        payloads={name:_local(fd,name)[0] for name in FILES}
        if sum(map(len,payloads.values()))>max_total_bytes or any(hashlib.sha256(data).hexdigest()!=value['sha256'][name] for name,data in payloads.items()):
            raise RuntimeError('Backup payload changed')
        validate_snapshot(parse_unique_json(payloads['auditor_state.json']))
        if not isinstance(parse_unique_json(payloads['saved-config.json']),dict):raise RuntimeError('Backup settings invalid')
        if _local(fd,'backup-complete.json')[0]!=raw:raise RuntimeError('Backup changed')
        if any(_local(fd,name)[0]!=data for name,data in payloads.items()):raise RuntimeError('Backup payload changed')
        current=_open_directory(str(root))
        try:
            observed=os.fstat(current)
            if (observed.st_dev,observed.st_ino)!=(info.st_dev,info.st_ino):raise RuntimeError('Backup directory changed')
        finally:os.close(current)
        captured=value.get('captured_at')
        try:
            parsed=datetime.fromisoformat(captured)
            if parsed.tzinfo is None:captured=None
        except (TypeError,ValueError):captured=None
        return {'captured_at':captured}
    finally:os.close(fd)
