"""Reject retained copy attempts despite freshly healthy three-domain checks.

Separate disposable VM only. No journal adoption, recovery transition, service
restoration or production permission. New private NFS guard fixture required.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys

from app import sqlite_disposable_maintenance_journal as journal
from app.sqlite_disposable_boundary_set import compose_disposable_boundaries
from app.sqlite_disposable_docker_backend import held_disposable_docker_observer
from app.sqlite_disposable_nfs_backend import held_disposable_nfs_observer
from app.sqlite_disposable_storage_backend import held_disposable_storage_observer
from app.sqlite_unified_disposable_controller import run_unified_disposable_copy
from scripts.sqlite_nfs4_guest_lab import require_guest
from scripts.sqlite_nfs_backend_guest_lab import prepare_guard_fixture, GUARD_DIGEST


def retained_bytes(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob('*') if path.is_file()}


def require_rejection(*, media, control, docker, nfs, expected):
    errors = {'controller': journal.MaintenanceControllerSessionChanged,
              'boot': journal.MaintenanceBootScopeChanged}
    if expected not in errors:
        raise ValueError('Explicit controller or boot rejection required')
    before = (retained_bytes(media), retained_bytes(control))
    with held_disposable_storage_observer(root=media) as storage:
        # Actually exercise all fresh adapters before testing retained admission.
        compose_disposable_boundaries(docker=docker, nfs=nfs, host_storage=storage)()
        def no_collection(*args, **kwargs):
            raise AssertionError('Retained attempt reached collection')
        try:
            run_unified_disposable_copy(docker=docker, nfs=nfs, host_storage=storage,
                root=media, database=media/'state.db', journal_root=control,
                maintenance_revision=3, operation_id='guest-copy', media_key='Synthetic Movie',
                title_folder='Synthetic Movie', jellyfin_type='Movie',
                thresholds={'Waiting':7,'Holding':7,'Removal':7,'Keep':0},
                fetch=no_collection, clock=lambda:datetime(2026,1,1))
        except errors[expected]:
            pass
        else:
            raise RuntimeError('Retained attempt unexpectedly admitted')
    if before != (retained_bytes(media), retained_bytes(control)):
        raise RuntimeError('Rejected recovery changed retained bytes')
    if (control/'release.fixture-receipt').exists():
        raise RuntimeError('Unexpected release receipt')


def run(*, retained_root, guard_root, docker_root, daemon_id, plugin, container_ids, expected):
    require_guest()
    if expected not in ('controller','boot'):
        raise ValueError('Explicit expected rejection required')
    retained_root, guard_root, docker_root = map(Path, (retained_root, guard_root, docker_root))
    if any(not p.is_absolute() or p.resolve()!=p for p in (retained_root,guard_root,docker_root)):
        raise ValueError('Canonical fixture paths required')
    if (docker_root/'media' not in retained_root.parents or guard_root==retained_root
            or guard_root in retained_root.parents or retained_root in guard_root.parents):
        raise ValueError('Separate new guard fixture and retained private writer media required')
    if not (retained_root/'result.json').is_file():
        raise RuntimeError('Completed prior combined fixture required')
    with held_disposable_docker_observer(root=docker_root,daemon_id=daemon_id,
                                        plugin=plugin,container_ids=container_ids) as docker:
        docker()
        prepare_guard_fixture(guard_root)
        with held_disposable_nfs_observer(root=guard_root,guard_sha256=GUARD_DIGEST) as nfs:
            for checkpoint in ('collection','publication','quarantine','completion'):
                fixture=retained_root/'copies'/checkpoint
                suffix='loss-'+checkpoint
                require_rejection(media=fixture/'media'/('copy-'+suffix),
                                  control=fixture/('copy-maintenance-'+suffix),
                                  docker=docker,nfs=nfs,expected=expected)
    result=dict(status='private_guest_unified_recovery_rejected',expected_rejection=expected,
                retained_attempts_checked=4,fresh_domains_observed=True,retained_bytes_unchanged=True,
                fixture_only=True,automatic_release=False,production_authorized=False,
                production_activation='disabled',writer_exclusion_verified=False,
                restart_inhibition_verified=False)
    (guard_root/'recovery-result.json').write_text(json.dumps(result,sort_keys=True))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('retained-root','guard-root','docker-root','daemon-id','plugin'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--container-id',action='append',required=True)
    parser.add_argument('--expected',choices=('controller','boot'),required=True)
    parser.add_argument('--worker',action='store_true')
    args=parser.parse_args()
    require_guest()
    if args.worker:
        print(json.dumps(run(retained_root=args.retained_root,guard_root=args.guard_root,
              docker_root=args.docker_root,daemon_id=args.daemon_id,plugin=args.plugin,
              container_ids=args.container_id,expected=args.expected),sort_keys=True))
    else:
        command=['unshare','--mount','--propagation','private',sys.executable,'-B','-m',
                 'scripts.sqlite_unified_recovery_guest_lab','--worker']
        for name in ('retained_root','guard_root','docker_root','daemon_id','plugin','expected'):
            command.extend(['--'+name.replace('_','-'),getattr(args,name)])
        for identity in args.container_id:command.extend(['--container-id',identity])
        subprocess.run(command,check=True,timeout=120)
