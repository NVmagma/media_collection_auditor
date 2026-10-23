"""Combine three live fixture observers inside the separate Linux VM.

An already fenced private Docker fixture is required; this script never starts,
reconfigures or stops Docker/NFS services. NFS dispatch mounts are new private
fixture paths, not actual Unraid startup entrypoints. No production permission.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from scripts.sqlite_nfs4_guest_lab import require_guest
from scripts.sqlite_nfs_backend_guest_lab import prepare_guard_fixture, GUARD_DIGEST
from scripts.sqlite_storage_copy_guest_lab import run as run_copy_cases
from app.sqlite_disposable_docker_backend import held_disposable_docker_observer
from app.sqlite_disposable_nfs_backend import held_disposable_nfs_observer


def run(*, root, docker_root, daemon_id, plugin, container_ids):
    require_guest()
    root = Path(root)
    docker_root = Path(docker_root)
    if (not root.is_absolute() or root.resolve() != root
            or not docker_root.is_absolute() or docker_root.resolve() != docker_root
            or docker_root / 'media' not in root.parents):
        raise ValueError('Canonical new fixture beneath private writer media required')
    # Refuse a missing/changed selected writer before creating NFS fixture mounts.
    with held_disposable_docker_observer(root=docker_root, daemon_id=daemon_id,
                                        plugin=plugin, container_ids=container_ids) as docker:
        docker()
        root.mkdir(mode=0o700)
        nfs_root = prepare_guard_fixture(root / 'nfs')
        with held_disposable_nfs_observer(root=nfs_root, guard_sha256=GUARD_DIGEST) as nfs:
            result = run_copy_cases(root / 'copies', docker=docker, nfs=nfs)
        (root / 'result.json').write_text(json.dumps(result, sort_keys=True))
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--docker-root', required=True)
    parser.add_argument('--daemon-id', required=True)
    parser.add_argument('--plugin', required=True)
    parser.add_argument('--container-id', action='append', required=True)
    parser.add_argument('--worker', action='store_true')
    args = parser.parse_args()
    require_guest()
    if args.worker:
        print(json.dumps(run(root=args.root, docker_root=args.docker_root,
                             daemon_id=args.daemon_id, plugin=args.plugin,
                             container_ids=args.container_id), sort_keys=True))
    else:
        command = ['unshare', '--mount', '--propagation', 'private', sys.executable,
                   '-B', '-m', 'scripts.sqlite_unified_copy_guest_lab', '--worker',
                   '--root', args.root, '--docker-root', args.docker_root,
                   '--daemon-id', args.daemon_id, '--plugin', args.plugin]
        for identity in args.container_id:
            command.extend(['--container-id', identity])
        subprocess.run(command, check=True, timeout=180)
