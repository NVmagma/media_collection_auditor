"""Owned-mount evidence for disposable dispatch recovery, never production authority."""
import ctypes
import hashlib
import json
import os
import struct

from app.sqlite_disposable_nfs_config_plan import _read, _write


def unique_mount_id(path):
    """Linux statx unique mount identity; never fall back to reusable IDs.

    Layout/mask: Linux UAPI include/uapi/linux/stat.h (v6.10).
    Only this optional disposable ownership mechanism requires the capability.
    """
    function=getattr(ctypes.CDLL(None,use_errno=True),'statx',None)
    if function is None:raise RuntimeError('Unique mount identity unavailable; retain fence')
    function.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_uint,ctypes.c_void_p]
    function.restype=ctypes.c_int
    data=ctypes.create_string_buffer(256)
    if function(-100,os.fsencode(path),0x100,0x4000,data)!=0:
        raise RuntimeError('Unique mount identity unavailable; retain fence')
    mask=struct.unpack_from('=I',data.raw,0)[0]
    identity=struct.unpack_from('=Q',data.raw,144)[0]
    if not mask & 0x4000 or identity==0:
        raise RuntimeError('Unique mount identity unavailable; retain fence')
    return identity


def _unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('Duplicate receipt key')
        result[key]=value
    return result


def receipt_name(route):
    from app.sqlite_disposable_offline_dispatch import ROUTES
    if route not in ROUTES:raise ValueError('Fixed dispatch route required')
    return 'installed-'+route+'.json'


def record_installed_mount(directory,route,pending,mount,unique_id):
    receipt=dict(schema_version=1,fixture_only=True,
                 request_sha256=hashlib.sha256(pending[0]).hexdigest(),
                 route=route,mount=list(mount),unique_mount_id=unique_id,production_authorized=False)
    _write(directory,receipt_name(route),(json.dumps(receipt,sort_keys=True)+'\n').encode())
    os.fsync(directory)
    return _read(directory,receipt_name(route))


def read_installed_mount(directory,route,pending):
    artifact=_read(directory,receipt_name(route))
    try:
        receipt=json.loads(artifact[0],object_pairs_hook=_unique)
        if (not isinstance(receipt,dict) or set(receipt)!={
                'schema_version','fixture_only','request_sha256','route','mount','unique_mount_id','production_authorized'}
                or type(receipt['schema_version']) is not int or receipt['schema_version']!=1
                or receipt['fixture_only'] is not True or receipt['production_authorized'] is not False
                or receipt['request_sha256']!=hashlib.sha256(pending[0]).hexdigest()
                or type(receipt['unique_mount_id']) is not int or not 0<receipt['unique_mount_id']<2**64
                or receipt['route']!=route or not isinstance(receipt['mount'],list)
                or len(receipt['mount'])!=6
                or not all(isinstance(value,str) for value in receipt['mount'])):
            raise ValueError()
        return tuple(receipt['mount']),receipt['unique_mount_id'],artifact
    except (ValueError,TypeError,KeyError,UnicodeError) as error:
        raise RuntimeError('Invalid owned-mount receipt; retain fence') from error


def review_disposable_controller_recovery(root):
    """Coordinate with the controller lock; inspect owned changes without restoring."""
    import fcntl
    import stat
    from app import sqlite_disposable_offline_dispatch as dispatch

    root=dispatch._root(root)
    directory=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    lock=None
    try:
        held=os.fstat(directory)
        marker=_read(directory,'.disposable_offline_dispatch')
        if marker[0]!=dispatch.MARKER:raise RuntimeError('Marked offline fixture required')
        # Never recreate a lost lock or adopt a running controller's attempt.
        lock=os.open('controller.lock',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
        lock_info=os.fstat(lock)
        if not stat.S_ISREG(lock_info.st_mode) or lock_info.st_nlink!=1:
            raise RuntimeError('Existing regular controller lock required')
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError('Controller lock held; recovery review refused') from error
        pending=_read(directory,'pending-request.json')
        request=dispatch._pending_request(pending[0])
        scope=dispatch._scope()
        review=dispatch.review_disposable_offline_dispatch(root)
        targets=dispatch._targets(root)
        def mounts():
            rows=dispatch._mount_rows()
            return {name:tuple(row for row in rows if row[4]==str(target))
                    for name,target in targets.items()}
        before=mounts()
        receipts={}
        unique_ids={}
        owned={}
        blockers=list(review['blockers'])
        for route in targets:
            try:
                recorded,unique_id,artifact=read_installed_mount(directory,route,pending)
            except FileNotFoundError:
                owned[route]='unreceipted_mount' if before[route] else 'no_mount_receipt'
                if before[route]:blockers.append('unreceipted_mount:'+route)
                continue
            receipts[route]=artifact
            observed_id=dispatch._unique_mount_id(targets[route])
            unique_ids[route]=observed_id
            if (unique_id!=observed_id or before[route]!=(recorded,)
                    or review['routes'][route]!='guard_bytes_observed_mount_ownership_unverified'):
                owned[route]='receipt_mount_conflict'
                blockers.append('receipt_mount_conflict:'+route)
            elif request['scope']!=list(scope):
                owned[route]='receipt_scope_changed'
            else:
                owned[route]='request_bound_guard_mount_observed'
                blockers.append('hidden_original_unverified:'+route)
        current=root.lstat()
        current_lock=os.stat('controller.lock',dir_fd=directory,follow_symlinks=False)
        if (not stat.S_ISDIR(current.st_mode)
                or (current.st_dev,current.st_ino)!=(held.st_dev,held.st_ino)
                or not stat.S_ISREG(current_lock.st_mode) or current_lock.st_nlink!=1
                or (current_lock.st_dev,current_lock.st_ino)!=(lock_info.st_dev,lock_info.st_ino)
                or _read(directory,'.disposable_offline_dispatch')!=marker
                or _read(directory,'pending-request.json')!=pending
                or any(_read(directory,receipt_name(route))!=artifact
                       for route,artifact in receipts.items())
                or any(os.path.lexists(root/receipt_name(route)) for route in targets if route not in receipts)
                or any(dispatch._unique_mount_id(targets[route])!=identity for route,identity in unique_ids.items())
                or dispatch._targets(root)!=targets or mounts()!=before or dispatch._scope()!=scope):
            raise RuntimeError('Controller recovery binding changed; retain fence')
        return {**review,'source':'retained_controller_request_and_mount_receipts',
                'mount_evidence':owned,'blockers':blockers,'controller_lock_verified':True,
                'controller_adoption_authorized':False,'restoration_authorized':False}
    finally:
        if lock is not None:os.close(lock)
        os.close(directory)
