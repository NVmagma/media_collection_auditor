"""Real disposable copy checkpoints with live Linux storage observations only.

Other external writer domains are not exercised here. This is not ownership
acceptance or production admission. Run only in the separate fixture VM.
"""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import subprocess
import sys

from scripts.sqlite_nfs4_guest_lab import require_guest
from scripts.sqlite_storage_backend_guest_lab import mount
from scripts.sqlite_docker_copy_guest_lab import run_copy_case
from app.sqlite_disposable_storage_backend import held_disposable_storage_observer
from app.sqlite_disposable_boundary_set import compose_disposable_boundaries


def run(root, *, docker=None, nfs=None):
    require_guest()
    combined = docker is not None or nfs is not None
    if combined and (not callable(docker) or not callable(nfs)):
        raise ValueError('Both external domain observers required')
    root = Path(root)
    if not root.is_absolute() or root.resolve() != root:
        raise ValueError('Canonical new guest fixture required')
    root.mkdir(mode=0o700)
    results = {}
    for checkpoint in ('healthy', 'collection', 'publication', 'quarantine', 'completion'):
        fixture = root / checkpoint
        fixture.mkdir()
        (fixture / '.disposable_writer').write_bytes(b'DISPOSABLE ONLY\n')
        (fixture / 'media').mkdir()
        suffix = 'healthy' if checkpoint == 'healthy' else 'loss-' + checkpoint
        media = fixture / 'media' / ('copy-' + suffix)
        baseline = fixture / 'stage-baseline'
        baseline.mkdir()
        with ExitStack() as stack:
            observer = None
            boundary = None
            def observe():
                nonlocal observer, boundary
                if observer is None:
                    # The copy helper creates its marked root before admission.
                    # Keep is unused by this waiting->holding synthetic title.
                    mount(baseline, media / 'keep')
                    observer = stack.enter_context(held_disposable_storage_observer(root=media))
                    boundary = (compose_disposable_boundaries(docker=docker, nfs=nfs,
                                host_storage=observer) if combined else observer)
                boundary()
            def lose():
                if observer is None:
                    raise RuntimeError('Storage baseline was never captured')
                mount(baseline, media / 'keep')  # Same inode, new mount ID.
            results[checkpoint] = run_copy_case(
                fixture, observe, lose_boundary=None if checkpoint == 'healthy' else lose,
                loss_at='collection' if checkpoint == 'healthy' else checkpoint)
    result = dict(status=('private_guest_unified_copy_verified' if combined
                          else 'private_guest_storage_copy_verified'), fixture_only=True,
                  storage_domain_only=not combined, network_collection_performed=False,
                  cases=results, production_authorized=False, production_activation='disabled',
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
                        '-B', '-m', 'scripts.sqlite_storage_copy_guest_lab',
                        '--worker', '--root', args.root], check=True, timeout=180)
