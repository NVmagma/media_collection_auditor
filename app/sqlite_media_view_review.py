"""Read-only comparison of two media views, never a mount or execution permit.

Compare directory/regular-file relative names and sizes, not media bytes. Refuse
symlinks, special files, unstable identities and bounded-resource exhaustion.
External writers are not excluded by matching observations.
"""
from contextlib import ExitStack
import os
import math
from pathlib import Path
import stat
from time import monotonic
from app.sqlite_scheduled_paths import _canonical,_open_directory
from app.sqlite_rename_mount_binding import read_fd_mount_id

STAGES=('Movies','Movies_hold','Movies_keep','Movies_removal','TV','TV_hold','TV_keep','TV_removal')


def _identity(info):return info.st_dev,info.st_ino,info.st_mtime_ns,info.st_ctime_ns


def compare_media_views(*,shared,native,maximum_entries=100000,maximum_seconds=60,timer=monotonic):
    base={'read_only':True,'automatic_action':'none','production_authorized':False,
          'media_actions_authorized':False,'mount_change_authorized':False,
          'byte_equality_verified':False,'external_writers_excluded':False}
    try:
        if type(maximum_entries) is not int or not 1<=maximum_entries<=100000:
            raise ValueError('Bounded inventory required')
        if type(maximum_seconds) not in (int,float) or not 0<maximum_seconds<=60:
            raise ValueError('Bounded observation required')
        start=timer();budget=0
        if not math.isfinite(start):raise ValueError('Finite timer required')
        def tick(entry=False):
            nonlocal budget
            if entry:budget+=1
            now=timer()
            if budget>maximum_entries*4 or not math.isfinite(now) or now<start or now-start>=maximum_seconds:
                raise RuntimeError('Inventory bound exceeded')
        roots=tuple(_canonical(str(value)) for value in (shared,native))
        with ExitStack() as stack:
            handles=[]
            for root in roots:
                fd=_open_directory(root);stack.callback(os.close,fd);handles.append(fd)
            original=[_identity(os.fstat(fd)) for fd in handles]
            if original[0][:2]==original[1][:2]:raise ValueError('Distinct media views required')
            native_mounts=set();native_devices=set()
            def capture(root):
                result={};moments={}
                def visit(fd,prefix,tree):
                    tick();before=_identity(os.fstat(fd));moments[(stage,*prefix)]=before
                    with os.scandir(fd) as entries:
                        names=[]
                        for entry in entries:
                            tick(entry=True);names.append(entry.name)
                            if len(names)>maximum_entries:raise RuntimeError('Directory bound exceeded')
                    for name in sorted(names):
                        tick();info=os.stat(name,dir_fd=fd,follow_symlinks=False)
                        relative=prefix+(name,);moments[(stage,*relative)]=_identity(info)
                        if stat.S_ISDIR(info.st_mode):
                            child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
                            try:
                                if _identity(os.fstat(child))!=_identity(info):raise RuntimeError('Directory changed')
                                tree[relative]=('directory',0);visit(child,relative,tree)
                            finally:os.close(child)
                        elif stat.S_ISREG(info.st_mode):
                            tree[relative]=('file',info.st_size)
                            if _identity(os.stat(name,dir_fd=fd,follow_symlinks=False))!=_identity(info):
                                raise RuntimeError('File changed')
                        else:raise RuntimeError('Unsupported media entry')
                    if _identity(os.fstat(fd))!=before:raise RuntimeError('Directory changed')
                for stage in STAGES:
                    tick();fd=os.open(stage,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=root)
                    try:
                        tree={};visit(fd,(),tree);result[stage]=tree
                        if root==handles[1]:
                            native_mounts.add(read_fd_mount_id(fd));native_devices.add(os.fstat(fd).st_dev)
                    finally:os.close(fd)
                return result,moments
            left_state=capture(handles[0]);right_state=capture(handles[1])
            if capture(handles[0])!=left_state or capture(handles[1])!=right_state:raise RuntimeError('Inventory changed')
            for index,path in enumerate(roots):
                fd=_open_directory(path)
                try:
                    if _identity(os.fstat(fd))!=original[index]:raise RuntimeError('View root changed')
                finally:os.close(fd)
            left,_=left_state;right,_=right_state
            reports=[]
            for stage in STAGES:
                a,b=left[stage],right[stage]
                reports.append({'stage':stage,'metadata_matches':a==b,
                    'shared_titles':sum(len(key)==1 and value[0]=='directory' for key,value in a.items()),
                    'native_titles':sum(len(key)==1 and value[0]=='directory' for key,value in b.items()),
                    'shared_entries':len(a),'native_entries':len(b)})
            return {**base,'status':'media_views_observed','all_stage_metadata_matches':left==right,
                'native_stages_one_mount_and_device':len(native_mounts)==len(native_devices)==1,
                'stages':reports}
    except Exception:
        return {**base,'status':'media_view_review_blocked','reason':'missing_unsupported_unstable_or_unbounded_inventory'}
