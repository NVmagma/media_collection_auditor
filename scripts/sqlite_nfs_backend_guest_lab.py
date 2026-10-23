"""Verify the NFS observer in a PRIVATE mount namespace of the separate VM.

Never Tower. No host settings operation, exports, NFSD controls or module loads.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from scripts.sqlite_nfs4_guest_lab import require_guest
from app.sqlite_disposable_nfs_backend import MARKER, _kernel_state, held_disposable_nfs_observer

GUARD_DIGEST='8a8cb6fa489a472e288fc1619e4bf9a2d2231282822c7c1952dfdd4f928022d2'


def run(root):
    require_guest()
    _kernel_state()  # Refuse a running/exporting guest; never stop it here.
    root=Path(root)
    if not root.is_absolute() or root.resolve()!=root:
        raise ValueError('Canonical new guest lab required')
    source=Path(__file__).with_name('sqlite_nfs_restart_guard.sh').read_bytes()
    if hashlib.sha256(source).hexdigest()!=GUARD_DIGEST:
        raise RuntimeError('Reviewed guard bytes differ')
    root.mkdir(mode=0o700)
    (root/'.disposable_nfs_guard').write_bytes(MARKER)
    (root/'guard-source').write_bytes(source);(root/'guard-source').chmod(0o500)
    for name in ('persistent.cfg','runtime.ini'):(root/name).write_bytes(b'shareNFSEnabled="no"\n')
    for name in ('dispatch-a','dispatch-b'):
        (root/name).touch()
        subprocess.run(['mount','--bind',str(root/'guard-source'),str(root/name)],check=True,capture_output=True)
        subprocess.run(['mount','-o','remount,bind,ro,nosuid,nodev',str(root/name)],check=True,capture_output=True)
    with held_disposable_nfs_observer(root=root,guard_sha256=GUARD_DIGEST) as verify:
        verify()
        denied=0
        for name in ('dispatch-a','dispatch-b'):
            for action in ('start','restart','update','reload','status','stop'):
                if subprocess.run([str(root/name),action],capture_output=True,timeout=5).returncode!=75:
                    raise RuntimeError('Private dispatch not denied')
                denied+=1
                verify()
        subprocess.run(['mount','-o','remount,bind,rw,nosuid,nodev',str(root/'dispatch-a')],check=True,capture_output=True)
        try:verify()
        except RuntimeError:pass
        else:raise RuntimeError('Writable guard mount unexpectedly admitted')
        subprocess.run(['mount','-o','remount,bind,ro,nosuid,nodev',str(root/'dispatch-a')],check=True,capture_output=True)
        try:verify()
        except RuntimeError as error:
            if 'retained review' not in str(error):raise
        else:raise RuntimeError('Failed observer automatically recovered')
    result={'status':'private_guest_nfs_backend_verified','fixture_only':True,
            'guarded_dispatches_denied':denied,'guard_mount_loss_blocked':True,
            'failed_observer_stayed_blocked':True,'production_authorized':False,
            'production_activation':'disabled','writer_exclusion_verified':False,
            'restart_inhibition_verified':False}
    (root/'result.json').write_text(json.dumps(result,sort_keys=True))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True)
    parser.add_argument('--worker',action='store_true')
    args=parser.parse_args()
    require_guest()
    if args.worker:print(json.dumps(run(args.root),sort_keys=True))
    else:
        subprocess.run(['unshare','--mount','--propagation','private',sys.executable,'-B','-m',
            'scripts.sqlite_nfs_backend_guest_lab','--worker','--root',args.root],check=True)
