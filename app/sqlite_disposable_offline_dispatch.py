"""One-shot guard installation beneath a marked disposable fake host tree.

No live host paths, settings handlers, service shutdown/startup or release API.
A durable pending request precedes mount operations. Fixture evidence only.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

from app.sqlite_disposable_nfs_config_plan import _read, _write
from app.sqlite_disposable_maintenance_journal import _linux_boot_id, _linux_network_namespace

MARKER=b'DISPOSABLE OFFLINE DISPATCH ONLY\n'
GUARD=b'''#!/bin/bash -p
printf '%s\\n' 'Offline maintenance service dispatch denied' >&2
exit 75
'''
ROUTES={
    'rc.docker':('usr/local/etc/rc.d/rc.docker',('etc/rc.d/rc.docker',)),
    'rc.nfsd':('usr/local/etc/rc.d/rc.nfsd',('etc/rc.d/rc.nfsd',)),
    'rc.samba':('usr/local/etc/rc.d/rc.samba',('etc/rc.d/rc.samba',)),
    'mover':('usr/local/sbin/mover',()),
    'mover.old':('usr/local/sbin/mover.old',()),
    'move-helper':('usr/libexec/unraid/move',()),
}
SERVICES=tuple(ROUTES)


def _root(root):
    root=Path(root)
    if (not root.is_absolute() or root.resolve()!=root
            or any(c.isspace() or c=='\\' for c in str(root))):
        raise ValueError('Canonical unescaped disposable root required')
    return root


def _scope():
    mount=os.readlink('/proc/self/ns/mnt')
    if not re.fullmatch(r'mnt:\[[0-9]+\]',mount):
        raise RuntimeError('Mount namespace unavailable')
    return (_linux_boot_id(),_linux_network_namespace(),mount)


def _targets(root):
    targets={}
    for name,(relative,aliases) in ROUTES.items():
        target=root/'host'/relative
        if target.parent.resolve()!=target.parent or target.resolve()!=target:
            raise RuntimeError('Disposable service directory changed')
        if any((root/'host'/alias).resolve()!=target for alias in aliases):
            raise RuntimeError('Disposable service alias binding changed')
        targets[name]=target
    return targets


def _mounts(targets):
    with open('/proc/self/mountinfo','rb') as stream:content=stream.read(1024*1024+1)
    if len(content)>1024*1024:raise RuntimeError('Mount inventory exceeds bound')
    found={name:[] for name in targets}
    for line in content.decode('utf-8').splitlines():
        halves=line.split(' - ')
        if len(halves)!=2:raise RuntimeError('Mount inventory malformed')
        fields=halves[0].split()
        if len(fields)<6:raise RuntimeError('Mount inventory malformed')
        for name,target in targets.items():
            if fields[4]==str(target):found[name].append(fields)
    result=[]
    for name,rows in found.items():
        if (len(rows)!=1 or not rows[0][0].isdigit()
                or not {'ro','nosuid','nodev'}.issubset(rows[0][5].split(','))):
            raise RuntimeError('Exact read-only service guard mount required')
        result.append((name,tuple(rows[0][:6])))
    return tuple(result)


def _pending_request(content):
    """Reject ambiguous or incomplete recovery evidence before inspecting mounts."""
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('Duplicate request key')
            result[key]=value
        return result
    try:
        request=json.loads(content,object_pairs_hook=unique)
        expected={'schema_version','fixture_only','phase','scope','root_identity',
                  'guard_sha256','originals','production_authorized','writer_exclusion_verified'}
        if not isinstance(request,dict) or set(request)!=expected:raise ValueError()
        if (type(request['schema_version']) is not int or request['schema_version']!=1
                or request['fixture_only'] is not True
                or request['production_authorized'] is not False
                or request['writer_exclusion_verified'] is not False
                or request['phase']!='fence_requested'):raise ValueError()
        def integers(value,length):
            return (isinstance(value,list) and len(value)==length
                    and all(type(n) is int and n>=0 for n in value))
        if not integers(request['root_identity'],2):raise ValueError()
        if (not isinstance(request['scope'],list) or len(request['scope'])!=3
                or not all(isinstance(v,str) and v for v in request['scope'])):raise ValueError()
        originals=request['originals']
        if not isinstance(originals,dict) or set(originals)!=set(ROUTES):raise ValueError()
        for original in originals.values():
            if (not isinstance(original,dict) or set(original)!={'sha256','identity'}
                    or not isinstance(original['sha256'],str)
                    or not re.fullmatch('[0-9a-f]{64}',original['sha256'])
                    or not integers(original['identity'],5)):raise ValueError()
        return request
    except (ValueError,TypeError,KeyError,UnicodeError) as error:
        raise RuntimeError('Invalid retained fixture request; review required') from error


def verify_disposable_offline_dispatch(root):
    """Read only; returning None is never an exclusion or recovery permit."""
    root=_root(root)
    directory=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        held=os.fstat(directory)
        marker=_read(directory,'.disposable_offline_dispatch')
        request_bytes,request_identity=_read(directory,'pending-request.json')
        if marker[0]!=MARKER:raise RuntimeError('Marked offline fixture required')
        request=_pending_request(request_bytes)
        if (request.get('schema_version')!=1 or request.get('fixture_only') is not True
                or request.get('phase')!='fence_requested'
                or request.get('scope')!=list(_scope())
                or request.get('root_identity')!=[held.st_dev,held.st_ino]
                or request.get('guard_sha256')!=hashlib.sha256(GUARD).hexdigest()):
            raise RuntimeError('Pending fixture scope changed')
        targets=_targets(root)
        first=_mounts(targets)
        for target in targets.values():
            parent=os.open(target.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try:
                if _read(parent,target.name)[0]!=GUARD:
                    raise RuntimeError('Service guard bytes changed')
            finally:os.close(parent)
        current=root.lstat()
        if (not stat.S_ISDIR(current.st_mode)
                or (current.st_dev,current.st_ino)!=(held.st_dev,held.st_ino)
                or _read(directory,'.disposable_offline_dispatch')!=marker
                or _read(directory,'pending-request.json')!=(request_bytes,request_identity)
                or _mounts(_targets(root))!=first or request['scope']!=list(_scope())):
            raise RuntimeError('Offline dispatch fixture binding changed')
    finally:os.close(directory)


@contextmanager
def install_disposable_offline_dispatch(root):
    """Retain mounts/request on all exits; no automatic restoration or adoption."""
    root=_root(root)
    directory=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    lock=None
    try:
        marker=_read(directory,'.disposable_offline_dispatch')
        if marker[0]!=MARKER:
            raise RuntimeError('Marked offline fixture required')
        if os.path.lexists(root/'pending-request.json'):
            raise RuntimeError('Retained request requires review; no reinstall')
        lock=os.open('controller.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK,
                     0o600,dir_fd=directory)
        info=os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:
            raise RuntimeError('Regular exclusive controller lock required')
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if os.path.lexists(root/'pending-request.json'):
            raise RuntimeError('Retained request requires review; no reinstall')
        targets=_targets(root)
        originals={}
        for name,target in targets.items():
            parent=os.open(target.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try:
                content,identity=_read(parent,target.name)
                originals[name]={'sha256':hashlib.sha256(content).hexdigest(),'identity':identity}
            finally:os.close(parent)
        guard,guard_identity=_read(directory,'deny-guard')
        if guard!=GUARD:raise RuntimeError('Exact disposable guard required')
        held=os.fstat(directory)
        request=dict(schema_version=1,fixture_only=True,phase='fence_requested',
                     scope=_scope(),root_identity=(held.st_dev,held.st_ino),
                     guard_sha256=hashlib.sha256(guard).hexdigest(),originals=originals,
                     production_authorized=False,writer_exclusion_verified=False)
        _write(directory,'pending-request.json',(json.dumps(request,sort_keys=True)+'\n').encode())
        os.fsync(directory)  # MUST precede every external mount action.
        pending=_read(directory,'pending-request.json')
        def binding():
            current=root.lstat()
            current_lock=os.stat('controller.lock',dir_fd=directory,follow_symlinks=False)
            if (not stat.S_ISDIR(current.st_mode)
                    or (current.st_dev,current.st_ino)!=(held.st_dev,held.st_ino)
                    or not stat.S_ISREG(current_lock.st_mode) or current_lock.st_nlink!=1
                    or (current_lock.st_dev,current_lock.st_ino)!=(info.st_dev,info.st_ino)
                    or _read(directory,'.disposable_offline_dispatch')!=marker
                    or _read(directory,'pending-request.json')!=pending
                    or _read(directory,'deny-guard')!=(guard,guard_identity)
                    or _targets(root)!=targets or request['scope']!=_scope()):
                raise RuntimeError('Fixture binding changed; request retained')
        for name,target in targets.items():
            binding()
            parent=os.open(target.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try:
                content,identity=_read(parent,target.name)
                if (identity!=originals[name]['identity']
                        or hashlib.sha256(content).hexdigest()!=originals[name]['sha256']):
                    raise RuntimeError('Original dispatch changed; request retained')
            finally:os.close(parent)
            subprocess.run(['mount','--bind',str(root/'deny-guard'),str(target)],
                           check=True,capture_output=True,timeout=10)
            binding()
            subprocess.run(['mount','-o','remount,bind,ro,nosuid,nodev',str(target)],
                           check=True,capture_output=True,timeout=10)
        binding()
        verify_disposable_offline_dispatch(root)
        yield
    finally:
        if lock is not None:os.close(lock)
        os.close(directory)
