"""Observe a marked NFS fence fixture; never configure services or clear holds.

Kernel state is read from this process's actual Linux namespaces. Guard mounts
and preferences are additional requirements, not complete ownership proof.
"""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import stat

from app.sqlite_disposable_maintenance_journal import _linux_boot_id, _linux_network_namespace
from app.sqlite_disposable_nfs_config_plan import _read
from app.sqlite_nfs_config_candidate import disabled_nfs_candidate

MARKER=b'DISPOSABLE NFS GUARD ONLY\n'


def _kernel_state():
    boot,network=_linux_boot_id(),_linux_network_namespace()
    mount=os.readlink('/proc/self/ns/mnt')
    if not re.fullmatch(r'mnt:\[[0-9]+\]',mount):
        raise RuntimeError('NFS mount namespace unavailable')
    with open('/proc/fs/nfsd/threads','rb') as stream:
        if stream.read(32).strip()!=b'0':
            raise RuntimeError('NFS server threads not stopped')
    with open('/proc/fs/nfsd/exports','rb') as stream:
        exports=stream.read(65537)
    if len(exports)>65536 or any(line.strip() and not line.lstrip().startswith(b'#') for line in exports.splitlines()):
        raise RuntimeError('NFS kernel export scope not empty')
    return boot,network,mount


def _guard_mounts(root):
    with open('/proc/self/mountinfo','rb') as stream:
        content=stream.read(1024*1024+1)
    if len(content)>1024*1024:
        raise RuntimeError('NFS guard mount inventory exceeds bound')
    lines=content.decode('utf-8').splitlines()
    identities=[]
    for name in ('dispatch-a','dispatch-b'):
        target=str(root/name)
        rows=[]
        for line in lines:
            pieces=line.split(' - ')
            if len(pieces)!=2:raise RuntimeError('NFS guard mount inventory malformed')
            fields=pieces[0].split()
            if len(fields)<6:raise RuntimeError('NFS guard mount inventory malformed')
            if fields[4]==target:rows.append(fields)
        if len(rows)!=1 or not {'ro','nosuid','nodev'}.issubset(set(rows[0][5].split(','))):
            raise RuntimeError('Exact read-only NFS guard mounts unavailable')
        if not rows[0][0].isdigit():raise RuntimeError('NFS guard mount identity invalid')
        identities.append(tuple(rows[0][:6]))
    return tuple(identities)


@contextmanager
def held_disposable_nfs_observer(*, root, guard_sha256):
    if not isinstance(guard_sha256,str) or not re.fullmatch(r'[0-9a-f]{64}',guard_sha256):
        raise ValueError('Explicit guard digest required')
    root=Path(root)
    if not root.is_absolute() or root.resolve()!=root or any(c.isspace() or c=='\\' for c in str(root)):
        raise ValueError('Canonical unescaped NFS guard fixture required')
    directory=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    failed=False
    try:
        held=os.fstat(directory)
        marker=_read(directory,'.disposable_nfs_guard')
        if marker[0]!=MARKER:raise RuntimeError('Marked NFS guard fixture required')
        def sample():
            current=root.lstat()
            if (not stat.S_ISDIR(current.st_mode)
                    or (current.st_dev,current.st_ino)!=(held.st_dev,held.st_ino)
                    or _read(directory,'.disposable_nfs_guard')!=marker):
                raise RuntimeError('NFS fixture root binding changed')
            preferences=[]
            for name in ('persistent.cfg','runtime.ini'):
                value,identity=_read(directory,name)
                if disabled_nfs_candidate(value)!=value:
                    raise RuntimeError('NFS preference not explicitly disabled')
                preferences.append(identity)
            guards=[]
            for name in ('dispatch-a','dispatch-b'):
                content,identity=_read(directory,name)
                if hashlib.sha256(content).hexdigest()!=guard_sha256:
                    raise RuntimeError('NFS guard content differs')
                guards.append(identity)
            return _kernel_state(),_guard_mounts(root),tuple(preferences),tuple(guards)
        expected=sample()
        def verify():
            nonlocal failed
            if failed:raise RuntimeError('NFS boundary failed; retained review required')
            try:
                if sample()!=expected or sample()!=expected:
                    raise RuntimeError('NFS live binding changed')
            except RuntimeError:
                failed=True
                raise
            except Exception:
                failed=True
                raise RuntimeError('NFS live observation unavailable; review required') from None
            except BaseException:
                failed=True
                raise
        yield verify
    finally:os.close(directory)
