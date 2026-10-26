"""Actual bind-overlay checks inside the separate VM's private mount namespace.

No production paths, service controls, exports or kernel module changes.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from scripts.sqlite_nfs4_guest_lab import require_guest
from app.sqlite_disposable_storage_backend import held_disposable_storage_observer
from app.sqlite_disposable_boundary_set import compose_disposable_boundaries


def mount(source, target):
    subprocess.run(['mount', '--bind', str(source), str(target)], check=True,
                   capture_output=True, timeout=10)


def unmount(target, *, detach=False):
    subprocess.run(['umount'] + (['-l'] if detach else []) + [str(target)], check=True, capture_output=True, timeout=10)


def run(root):
    require_guest()
    root = Path(root)
    if not root.is_absolute() or root.resolve() != root:
        raise ValueError('Canonical new guest fixture required')
    root.mkdir(mode=0o700)
    media = root / 'media'
    media.mkdir()
    (media / '.sqlite_disposable_rehearsal').write_bytes(b'DISPOSABLE ONLY\n')
    for name in ('transient', 'holding', 'keep', 'removal'):
        (media / name).mkdir()
    # A separate bind mount at capture is permitted, including a different
    # mount ID for a stage. No assumption that every directory shares a mount.
    baseline = root / 'baseline'
    baseline.mkdir()
    (baseline / 'payload').write_bytes(b'original fixture\n')
    mount(baseline, media / 'holding')
    with held_disposable_storage_observer(root=media) as verify:
        verify()
        if (media / 'holding' / 'payload').read_bytes() != b'original fixture\n':
            raise RuntimeError('Baseline mount not readable')
        # Same device AND inode, different mount ID: inode-only checks miss it.
        before = (media / 'holding').stat()
        mount(baseline, media / 'holding')
        try:
            after = (media / 'holding').stat()
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise RuntimeError('Same-inode overlay case not established')
            combined = compose_disposable_boundaries(
                docker=lambda: None, nfs=lambda: None, host_storage=verify)
            try:
                combined()
            except RuntimeError as error:
                if 'host_storage' not in str(error):
                    raise
            else:
                raise RuntimeError('Overlay admitted by combined observer')
        finally:
            unmount(media / 'holding')
        try:
            verify()
        except RuntimeError as error:
            if 'failed' not in str(error):
                raise
        else:
            raise RuntimeError('Failed observer recovered after unmount')
    # A fresh independent observation is only fixture evidence, not clearance.
    with held_disposable_storage_observer(root=media) as verify:
        verify()
        # Held descriptors make ordinary unmount busy. Detach ONLY this new
        # fixture mount, reproducing path loss while descriptors stay alive.
        unmount(media / 'holding', detach=True)
        try:
            verify()
        except RuntimeError:
            pass
        else:
            raise RuntimeError('Baseline mount loss admitted')
    if (baseline / 'payload').read_bytes() != b'original fixture\n':
        raise RuntimeError('Original fixture changed')
    result = dict(status='private_guest_storage_backend_verified', fixture_only=True,
                  mixed_mount_baseline_accepted=True, same_inode_overlay_rejected=True,
                  combined_domain_rejected=True, baseline_mount_loss_rejected=True,
                  failed_observer_stayed_blocked=True, original_bytes_unchanged=True,
                  production_authorized=False, production_activation='disabled',
                  writer_exclusion_verified=False, restart_inhibition_verified=False)
    (root / 'result.json').write_text(json.dumps(result, sort_keys=True))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--worker', action='store_true')
    args = parser.parse_args()
    require_guest()
    if args.worker:
        print(json.dumps(run(args.root), sort_keys=True))
    else:
        subprocess.run(['unshare', '--mount', '--propagation', 'private', sys.executable,
                        '-B', '-m', 'scripts.sqlite_storage_backend_guest_lab',
                        '--worker', '--root', args.root], check=True, timeout=60)
