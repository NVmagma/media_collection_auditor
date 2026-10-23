"""Extract a cached-image archive into a NEW marked disposable runtime only.

Invoked inside a restricted packaging container. Never execute image code here,
read host settings, mount host paths or authorize production work.
"""
import argparse
import json
import os
from pathlib import Path
import posixpath
import tarfile

MARKER=b'DISPOSABLE CONTROLLER RUNTIME ONLY\n'
MAX_BYTES=2*1024**3
MAX_ENTRIES=100000
SMOKE=b'''import fcntl, json, os, sqlite3, sys
if sys.version_info < (3,12): raise RuntimeError("Python 3.12 required")
lock=os.open("/tmp/controller-smoke.lock",os.O_CREAT|os.O_EXCL|os.O_RDWR,0o600)
fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
other=os.open("/tmp/controller-smoke.lock",os.O_RDWR)
try:
    fcntl.flock(other,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError: pass
else: raise RuntimeError("Exclusive lock unavailable")
os.close(other)
fd=os.open("/tmp/controller-smoke.db",os.O_CREAT|os.O_EXCL|os.O_RDWR,0o600)
os.close(fd)
with sqlite3.connect("/tmp/controller-smoke.db") as db:
    db.execute("PRAGMA synchronous=FULL")
    db.execute("CREATE TABLE fixture(value TEXT NOT NULL)")
    db.execute("INSERT INTO fixture VALUES ('synthetic only')")
with sqlite3.connect("file:/tmp/controller-smoke.db?mode=ro",uri=True) as db:
    if db.execute("SELECT value FROM fixture").fetchall()!=[("synthetic only",)]:
        raise RuntimeError("SQLite checkpoint unavailable")
print(json.dumps(dict(status="disposable_host_runtime_verified",fixture_only=True,
    python_version=sys.version.split()[0],sqlite_version=sqlite3.sqlite_version,
    exclusive_lock_verified=True,sqlite_checkpoint_verified=True,
    production_authorized=False,production_activation="disabled",
    writer_exclusion_verified=False,automatic_action="none"),sort_keys=True))
os.close(lock)
'''


def prepare(root):
    root=Path(root)
    if not root.is_absolute() or root.resolve()!=root:
        raise ValueError('Canonical disposable runtime root required')
    marker=root/'.disposable_controller_runtime'
    if marker.is_symlink() or marker.read_bytes()!=MARKER:
        raise RuntimeError('Disposable runtime marker required')
    archive=root/'image.tar'
    if archive.is_symlink() or not archive.is_file() or archive.stat().st_size>MAX_BYTES:
        raise RuntimeError('Bounded regular image archive required')
    destination=root/'rootfs'
    destination.mkdir(mode=0o700)  # Never adopt or overwrite a prior extraction.
    with tarfile.open(archive,mode='r:') as source:
        count=total=0
        # data_filter rejects traversal, escaping links and device entries.
        # Stream members so a hostile archive cannot require an unbounded list.
        for member in source:
            count+=1;total+=max(0,member.size)
            if count>MAX_ENTRIES or total>MAX_BYTES:
                raise RuntimeError('Runtime archive expansion exceeds bound')
            if member.name.startswith('/'):
                raise RuntimeError('Absolute archive entry rejected')
            if member.issym() and member.linkname.startswith('/'):
                # Image links are absolute within the future chroot. Convert
                # to equivalent contained relative links before data_filter.
                target=posixpath.normpath(member.linkname).lstrip('/')
                parent=posixpath.dirname(member.name) or '.'
                member=member.replace(linkname=posixpath.relpath(target or '.',parent))
            source.extract(member,path=destination,filter='data')
    interpreter=destination/'usr/local/bin/python3'
    resolved=interpreter.resolve(strict=True)
    if destination not in resolved.parents or not resolved.is_file() or not os.access(resolved,os.X_OK):
        raise RuntimeError('Contained executable interpreter required')
    smoke=destination/'controller-smoke.py'
    with smoke.open('xb') as output:
        output.write(SMOKE)
    return dict(status='disposable_runtime_prepared',fixture_only=True,
                production_authorized=False,production_activation='disabled')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True)
    args=parser.parse_args()
    print(json.dumps(prepare(args.root),sort_keys=True))
