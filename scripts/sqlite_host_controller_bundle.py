"""Build a new stdlib-only host preparation bundle; never install or activate it."""
import argparse
import hashlib
import json
import os
from pathlib import Path

from app.sqlite_disposable_nfs_config_plan import _read, _write

MODULES=(
    'app/sqlite_host_controller.py',
    'app/sqlite_disposable_maintenance_journal.py',
    'app/sqlite_lock.py',
    'app/sqlite_disposable_dispatch_recovery.py',
    'app/sqlite_disposable_nfs_config_plan.py',
    'app/sqlite_nfs_config_candidate.py',
)
BOOTSTRAP=('''"""Fixed preparation/review entry point. No external action commands."""
import argparse, hashlib, json, os, stat, sys, time
from pathlib import Path
if sys.version_info < (3,12):raise RuntimeError("Reviewed host runtime requires Python 3.12 or newer")
ROOT=Path(__file__).resolve().parent
FILES='''+repr((*MODULES,'controller.py'))+'''
def unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise RuntimeError("Duplicate package manifest key")
        result[key]=value
    return result
def bounded(path,limit):
    if path.resolve()!=path:raise RuntimeError("Canonical package path required")
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_size>limit:
            raise RuntimeError("Bounded single-link package file required")
        content=os.read(fd,limit+1)
        after=os.fstat(fd);current=path.lstat()
        def identity(info):
            return (info.st_dev,info.st_ino,info.st_mode,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
        if len(content)!=before.st_size or identity(before)!=identity(after) or identity(before)!=identity(current):
            raise RuntimeError("Package artifact changed")
        return content
    finally:os.close(fd)
manifest=json.loads(bounded(ROOT/"bundle.json",16384),object_pairs_hook=unique)
if (not isinstance(manifest,dict) or set(manifest)!={"schema_version","mode","files","production_authorized"}
        or type(manifest["schema_version"]) is not int or manifest["schema_version"]!=1
        or manifest["mode"]!="preparation_only" or manifest["production_authorized"] is not False
        or not isinstance(manifest["files"],dict) or set(manifest["files"])!=set(FILES)):
    raise RuntimeError("Exact preparation bundle manifest required")
for name in FILES:
    path=ROOT/name
    if hashlib.sha256(bounded(path,1048576)).hexdigest()!=manifest["files"][name]:
        raise RuntimeError("Controller bundle source mismatch")
sys.path.insert(0,str(ROOT))
from app.sqlite_host_controller import prepare_host_controller, review_host_controller
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("mode",choices=("prepare","review"))
parser.add_argument("--root",required=True)
parser.add_argument("--hold",action="store_true",help="Hold preparation lock; no external actions")
args=parser.parse_args()
if args.hold and args.mode!="prepare":parser.error("--hold requires prepare")
if args.mode=="prepare":
    with prepare_host_controller(args.root) as session:
        print(json.dumps(session.report(),sort_keys=True),flush=True)
        while args.hold:
            time.sleep(1)
            session.check()
else:
    print(json.dumps(review_host_controller(args.root),sort_keys=True))
''').encode()


def build(destination):
    destination=Path(destination)
    if not destination.is_absolute() or destination.resolve()!=destination:
        raise ValueError('New canonical absolute bundle directory required')
    checkout=Path(__file__).resolve().parents[1]
    source={}
    for name in MODULES:
        path=checkout/name
        if path.resolve()!=path:raise RuntimeError('Canonical bundle source required')
        directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:source[name]=_read(directory,path.name)
        finally:os.close(directory)
    destination.mkdir(mode=0o700)
    (destination/'app').mkdir(mode=0o700)
    digest={}
    for name,content in [(name,artifact[0]) for name,artifact in source.items()]+[('controller.py',BOOTSTRAP)]:
        path=destination/name
        directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            _write(directory,path.name,content)
            if _read(directory,path.name)[0]!=content:raise RuntimeError('Bundle artifact changed')
            os.fsync(directory)
        finally:os.close(directory)
        digest[name]=hashlib.sha256(content).hexdigest()
    directory=os.open(destination,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    parent=os.open(destination.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        manifest=dict(schema_version=1,mode='preparation_only',files=digest,production_authorized=False)
        manifest_bytes=(json.dumps(manifest,sort_keys=True)+'\n').encode()
        _write(directory,'bundle.json',manifest_bytes)
        os.fsync(directory);os.fsync(parent)
    finally:os.close(directory);os.close(parent)
    # Do not report a mixed source snapshot if files changed during packaging.
    for name,artifact in source.items():
        path=checkout/name
        directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            if _read(directory,path.name)!=artifact:raise RuntimeError('Source changed; retain package for review')
        finally:os.close(directory)
    return dict(status='host_preparation_bundle_created',module_count=len(MODULES),
                entrypoint_sha256=digest['controller.py'],
                bundle_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),production_authorized=False,
                service_controls_included=False,media_operations_included=False,
                installation_authorized=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination',required=True)
    print(json.dumps(build(parser.parse_args().destination),sort_keys=True))
