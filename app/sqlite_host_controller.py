"""Host controller preparation core. No service, media, release or resume API.

A retained maintenance request denies action; it never establishes ownership of
external writers. Deployment/location and actual host adapters remain unverified.
"""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import stat
from uuid import UUID

from app.sqlite_disposable_maintenance_journal import _linux_boot_id, _linux_network_namespace
from app.sqlite_disposable_dispatch_recovery import unique_mount_id
from app.sqlite_disposable_nfs_config_plan import _read, _write

MARKER=b'MEDIA AUDITOR HOST CONTROLLER PREPARATION ONLY\n'
_SESSION=secrets.token_hex(32)
BLOCKERS=('private_host_control_location_unverified','native_host_runtime_binding_unverified',
          'host_service_adapters_unimplemented',
          'production_boot_writer_fence_unimplemented','fresh_protection_provider_unverified',
          'production_controller_recovery_unimplemented')


def _root(path):
    path=Path(path)
    if not path.is_absolute() or path.resolve()!=path:
        raise ValueError('Canonical absolute control directory required')
    return path


def _scope():
    mount=os.readlink('/proc/self/ns/mnt')
    if not re.fullmatch(r'mnt:\[[1-9][0-9]*\]',mount):
        raise RuntimeError('Linux mount namespace unavailable')
    return (_linux_boot_id(),_linux_network_namespace(),mount)


def _private(info,directory=False):
    expected=stat.S_ISDIR if directory else stat.S_ISREG
    if (not expected(info.st_mode) or info.st_uid!=os.geteuid()
            or stat.S_IMODE(info.st_mode)!=(0o700 if directory else 0o600)
            or (not directory and info.st_nlink!=1)):
        raise RuntimeError('Private owned control artifact required')


def _artifact(directory,name):
    _private(os.stat(name,dir_fd=directory,follow_symlinks=False))
    result=_read(directory,name)
    _private(os.stat(name,dir_fd=directory,follow_symlinks=False))
    return result


def _unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('Duplicate control key')
        result[key]=value
    return result


def _request(content):
    try:
        value=json.loads(content,object_pairs_hook=_unique)
        if (not isinstance(value,dict) or set(value)!={
                'schema_version','kind','phase','request_id','controller_session','controller_pid',
                'scope','root_identity','root_unique_mount_id','production_authorized','external_actions_authorized'}
                or type(value['schema_version']) is not int or value['schema_version']!=1
                or value['kind']!='host_controller_preparation' or value['phase']!='maintenance_requested'
                or value['production_authorized'] is not False or value['external_actions_authorized'] is not False):
            raise ValueError()
        for name in ('request_id','controller_session'):
            if not isinstance(value[name],str) or not re.fullmatch('[0-9a-f]{64}',value[name]):raise ValueError()
        for name in ('controller_pid','root_unique_mount_id'):
            if type(value[name]) is not int or not 0<value[name]<2**64:raise ValueError()
        identity=value['root_identity']
        if (not isinstance(identity,list) or len(identity)!=2
                or not all(type(n) is int and n>=0 for n in identity)):raise ValueError()
        scope=value['scope']
        if not isinstance(scope,list) or len(scope)!=3 or not all(isinstance(v,str) for v in scope):
            raise ValueError()
        boot=UUID(scope[0])
        if str(boot)!=scope[0] or boot.int==0:raise ValueError()
        if not re.fullmatch(r'net:\[[1-9][0-9]*\]',scope[1]):raise ValueError()
        if not re.fullmatch(r'mnt:\[[1-9][0-9]*\]',scope[2]):raise ValueError()
        return value
    except (ValueError,TypeError,KeyError,UnicodeError) as error:
        raise RuntimeError('Invalid retained controller request; no repair or adoption') from error


def _report(request,scope,root_identity,mount_id):
    matches={'linux_boot':request['scope'][0]==scope[0],
             'network_namespace':request['scope'][1]==scope[1],
             'mount_namespace':request['scope'][2]==scope[2],
             'control_directory':request['root_identity']==list(root_identity),
             'control_mount':request['root_unique_mount_id']==mount_id,
             'controller_session':request['controller_session']==_SESSION and request['controller_pid']==os.getpid()}
    return dict(status='blocked',phase=request['phase'],request_id=request['request_id'],
                scope_matches=matches,blockers=[*BLOCKERS,*('scope_changed:'+key for key,ok in matches.items() if not ok)],
                automatic_action='none',production_activation='disabled',production_authorized=False,
                external_actions_authorized=False,controller_adoption_authorized=False,
                restoration_authorized=False,writer_exclusion_verified=False)


class PreparationSession:
    """Live handle only; never reconstructed from a retained request."""
    def __init__(self,root,directory,lock,request,marker,pending,scope,mount_id):
        self.root=root;self.directory=directory;self.lock=lock;self.request=request
        self.marker=marker;self.pending=pending;self.scope=scope;self.mount_id=mount_id
        self.root_info=os.fstat(directory);self.lock_info=os.fstat(lock)
        self.failed=False;self.closed=False

    def check(self):
        if self.failed or self.closed:raise RuntimeError('Controller session unavailable; retain request')
        try:
            current=self.root.lstat();_private(current,directory=True)
            current_lock=os.stat('controller.lock',dir_fd=self.directory,follow_symlinks=False)
            _private(current_lock)
            if ((current.st_dev,current.st_ino)!=(self.root_info.st_dev,self.root_info.st_ino)
                    or (current_lock.st_dev,current_lock.st_ino)!=(self.lock_info.st_dev,self.lock_info.st_ino)
                    or _artifact(self.directory,'.host_controller')!=self.marker
                    or _artifact(self.directory,'maintenance-request.json')!=self.pending
                    or _request(self.pending[0])!=self.request
                    or _scope()!=self.scope or unique_mount_id(self.root)!=self.mount_id
                    or self.request['controller_pid']!=os.getpid()
                    or self.request['controller_session']!=_SESSION):
                raise RuntimeError('Controller binding changed; retain request')
        except BaseException:
            self.failed=True
            raise

    def report(self):
        self.check()
        return _report(self.request,self.scope,(self.root_info.st_dev,self.root_info.st_ino),self.mount_id)


@contextmanager
def prepare_host_controller(root):
    """Create NEW private preparation state and hold its controller lock.

    Existing/partial directories are never repaired or adopted. No external action
    follows this request in the current implementation, even on a healthy host.
    """
    root=_root(root)
    scope=_scope()  # Capability failures precede any control state creation.
    mount_id=unique_mount_id(root.parent)
    directory=lock=None;session=None
    parent=os.open(root.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        os.mkdir(root.name,0o700,dir_fd=parent)
        os.fsync(parent)
        directory=os.open(root.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
        held=os.fstat(directory);_private(held,directory=True)
        if unique_mount_id(root)!=mount_id:raise RuntimeError('Control mount changed during preparation')
        _write(directory,'.host_controller',MARKER)
        lock=os.open('controller.lock',os.O_CREAT|os.O_EXCL|os.O_RDWR|os.O_NOFOLLOW,0o600,dir_fd=directory)
        _private(os.fstat(lock));fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        request=dict(schema_version=1,kind='host_controller_preparation',phase='maintenance_requested',
                     request_id=secrets.token_hex(32),controller_session=_SESSION,controller_pid=os.getpid(),
                     scope=scope,root_identity=(held.st_dev,held.st_ino),root_unique_mount_id=mount_id,
                     production_authorized=False,external_actions_authorized=False)
        _write(directory,'maintenance-request.json',(json.dumps(request,sort_keys=True)+'\n').encode())
        os.fsync(lock);os.fsync(directory);os.fsync(parent)
        pending=_artifact(directory,'maintenance-request.json')
        request=_request(pending[0])
        session=PreparationSession(root,directory,lock,request,_artifact(directory,'.host_controller'),pending,scope,mount_id)
        session.check()
        yield session
        session.check()
    finally:
        if session is not None:session.closed=True
        if lock is not None:os.close(lock)
        if directory is not None:os.close(directory)
        os.close(parent)


def review_host_controller(root):
    """Read retained state under its existing lock; no repair, replay or action."""
    root=_root(root)
    directory=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    lock=None
    try:
        held=os.fstat(directory);_private(held,directory=True)
        marker=_artifact(directory,'.host_controller')
        if marker[0]!=MARKER:raise RuntimeError('Host controller marker required')
        lock=os.open('controller.lock',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
        _private(os.fstat(lock))
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as error:raise RuntimeError('Live controller lock held; review refused') from error
        pending=_artifact(directory,'maintenance-request.json')
        request=_request(pending[0]);scope=_scope();mount_id=unique_mount_id(root)
        # Reuse live binding checks for the review snapshot, without treating the
        # retained session/PID as the new reviewer's authority.
        current=root.lstat();_private(current,directory=True)
        current_lock=os.stat('controller.lock',dir_fd=directory,follow_symlinks=False)
        _private(current_lock);held_lock=os.fstat(lock)
        if ((current.st_dev,current.st_ino)!=(held.st_dev,held.st_ino)
                or (current_lock.st_dev,current_lock.st_ino)!=(held_lock.st_dev,held_lock.st_ino)
                or _artifact(directory,'.host_controller')!=marker
                or _artifact(directory,'maintenance-request.json')!=pending
                or _scope()!=scope or unique_mount_id(root)!=mount_id):
            raise RuntimeError('Controller review changed; retain request')
        return {**_report(request,scope,(held.st_dev,held.st_ino),mount_id),'read_only':True}
    finally:
        if lock is not None:os.close(lock)
        os.close(directory)
