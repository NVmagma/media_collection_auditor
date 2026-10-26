"""Prepare private before/after artifacts from a marked disposable config only."""
import hashlib
import json
import os
from pathlib import Path
import stat

from app.sqlite_nfs_config_candidate import LIMIT, disabled_nfs_candidate, reviewed_restore_candidate

MARKER=b'DISPOSABLE HOST CONFIG ONLY\n'


def _identity(info):
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:
        raise RuntimeError('Single-link regular configuration artifact required')
    return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)


def _read(directory,name):
    fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
    try:
        identity=_identity(os.fstat(fd))
        content=os.read(fd,LIMIT+1)
        if (len(content)>LIMIT or len(content)!=identity[2] or _identity(os.fstat(fd))!=identity
                or _identity(os.stat(name,dir_fd=directory,follow_symlinks=False))!=identity):
            raise RuntimeError('Configuration artifact changed or exceeds bound')
        return content,identity
    finally:os.close(fd)


def _write(directory,name,content):
    fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=directory)
    try:
        remaining=memoryview(content)
        while remaining:
            written=os.write(fd,remaining)
            if not written:raise RuntimeError('Configuration artifact write incomplete')
            remaining=remaining[written:]
        os.fsync(fd)
    finally:os.close(fd)


def _prepare_disposable_config_plan(root, *, source_name, plan_name, transform, restore, status):
    root=Path(root)
    if not root.is_absolute() or root.resolve()!=root:
        raise ValueError('Canonical disposable configuration root required')
    directory=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    plan=None
    try:
        held=os.fstat(directory)
        marker,marker_id=_read(directory,'.disposable_host_config')
        if marker!=MARKER:raise RuntimeError('Marked disposable host configuration required')
        original,source_id=_read(directory,source_name)
        disabled=transform(original)
        os.mkdir(plan_name,mode=0o700,dir_fd=directory)
        plan=os.open(plan_name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=directory)
        _write(plan,'before.cfg',original)
        _write(plan,'disabled-candidate.cfg',disabled)
        manifest={'schema_version':1,'fixture_only':True,'source_identity':source_id,'source_name':source_name,
                  'before_sha256':hashlib.sha256(original).hexdigest(),
                  'candidate_sha256':hashlib.sha256(disabled).hexdigest(),
                  'requires_change':disabled!=original,'apply_authorized':False}
        manifest_content=(json.dumps(manifest,sort_keys=True)+'\n').encode()
        _write(plan,'manifest.json',manifest_content)
        plan_stat=os.fstat(plan)
        current_plan=os.stat(plan_name,dir_fd=directory,follow_symlinks=False)
        if (not stat.S_ISDIR(current_plan.st_mode)
                or (current_plan.st_dev,current_plan.st_ino)!=(plan_stat.st_dev,plan_stat.st_ino)
                or _read(plan,'before.cfg')[0]!=original
                or _read(plan,'disabled-candidate.cfg')[0]!=disabled
                or _read(plan,'manifest.json')[0]!=manifest_content):
            raise RuntimeError('Configuration plan binding/content changed')
        current=root.lstat()
        if ((current.st_dev,current.st_ino)!=(held.st_dev,held.st_ino)
                or _read(directory,'.disposable_host_config')!=(marker,marker_id)
                or _read(directory,source_name)!=(original,source_id)):
            raise RuntimeError('Configuration source binding changed; retain artifacts for review')
        os.fsync(plan);os.fsync(directory)
        if restore(original=original,disabled=disabled,current=disabled)!=original:
            raise RuntimeError('Exact restoration candidate verification failed')
        return {'status':status,'fixture_only':True,
                'source_unchanged':True,'requires_change':disabled!=original,
                'read_only_source':True,'apply_authorized':False,'restoration_authorized':False,
                'production_authorized':False,'production_activation':'disabled',
                'writer_exclusion_verified':False,'automatic_action':'none'}
    finally:
        if plan is not None:os.close(plan)
        os.close(directory)


def prepare_disposable_nfs_config_plan(root):
    return _prepare_disposable_config_plan(root, source_name='share.cfg', plan_name='nfs-plan',
        transform=disabled_nfs_candidate, restore=reviewed_restore_candidate,
        status='disposable_nfs_config_candidates_prepared')
