"""Guard only fake host paths in the separate VM; kill the installer, not services."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import socket
import subprocess
import sys

from app import sqlite_disposable_offline_dispatch as dispatch
from app.sqlite_disposable_dispatch_recovery import review_disposable_controller_recovery
from app.sqlite_disposable_offline_dispatch import (
    GUARD, MARKER, install_disposable_offline_dispatch, verify_disposable_offline_dispatch,
)
from scripts.sqlite_nfs4_guest_lab import require_guest


def require_dispatch_lab(root):
    """Also accept the dedicated, host-mount-free dispatch test container."""
    if (sys.platform=='linux' and os.geteuid()==0
            and socket.gethostname()=='mca-dispatch-fixture'
            and Path('/.dockerenv').is_file()
            and Path(root).parent==Path('/fixture')
            and Path('/fixture/code/dispatch-container-fixture').read_bytes()==b'DISPOSABLE DISPATCH CONTAINER ONLY\n'):
        rows=Path('/proc/self/mountinfo').read_text().splitlines()
        fixture=[row for row in rows if row.split()[4]=='/fixture']
        if (len(fixture)!=1 or fixture[0].split(' - ')[1].split()[0]!='tmpfs'
                or any('shared:' in row.split(' - ')[0] for row in rows)):
            raise RuntimeError('Private disposable tmpfs mount namespace required')
        return
    require_guest()


def prepare(root):
    root=Path(root)
    if not root.is_absolute() or root.resolve()!=root:
        raise ValueError('Canonical new fixture required')
    root.mkdir(mode=0o700)
    (root/'.disposable_offline_dispatch').write_bytes(MARKER)
    (root/'deny-guard').write_bytes(GUARD);(root/'deny-guard').chmod(0o500)
    direct=root/'host/usr/local/etc/rc.d';direct.mkdir(parents=True)
    (root/'host/etc').mkdir()
    (root/'host/etc/rc.d').symlink_to('../usr/local/etc/rc.d')
    for relative,_ in dispatch.ROUTES.values():
        target=root/'host'/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        # Even a broken guard can execute only this inert fixture stub.
        target.write_bytes(b'#!/bin/bash\nprintf "UNGUARDED FIXTURE\\n"\nexit 99\n')
        target.chmod(0o500)
    return root


def dispatches(root, *, partial=False):
    if partial:
        try:verify_disposable_offline_dispatch(root)
        except RuntimeError as error:
            if str(error)!='Exact read-only service guard mount required':raise
        else:raise RuntimeError('Partial guard installation accepted')
    else:verify_disposable_offline_dispatch(root)
    count=0
    actions={'rc.docker':('start','stop','force_stop','restart','status'),
             'rc.nfsd':('start','stop','restart','reload','update','status'),
             'rc.samba':(None,'start','stop','restart','reload','update','status','unrecognized')}
    if partial:actions={name:commands for name,commands in actions.items() if name=='rc.docker'}
    for alias in ('etc/rc.d','usr/local/etc/rc.d'):
        for service,commands in actions.items():
            for action in commands:
                result=subprocess.run([str(root/'host'/alias/service)]+([] if action is None else [action]),
                                      capture_output=True,timeout=5)
                if result.returncode!=75 or b'UNGUARDED' in result.stdout:
                    raise RuntimeError('Fixture dispatch not denied')
                if not partial:verify_disposable_offline_dispatch(root)
                count+=1
    if not partial:
        for route in ('mover','mover.old','move-helper'):
            relative,_=dispatch.ROUTES[route]
            commands=(None,) if route=='move-helper' else (None,'start','stop','status','unrecognized')
            for action in commands:
                result=subprocess.run([str(root/'host'/relative)]+([] if action is None else [action]),
                    input=b'/SYNTHETIC_ONLY/no_existing_file\n' if route=='move-helper' else None,
                    capture_output=True,timeout=5)
                if result.returncode!=75 or b'UNGUARDED' in result.stdout:
                    raise RuntimeError('Fixture mover dispatch not denied')
                verify_disposable_offline_dispatch(root)
                count+=1
    return count


def run(root, *, partial=False):
    require_dispatch_lab(root)
    root=prepare(root)
    diagnostic=(root/'installer.log').open('xb')
    worker=subprocess.Popen([sys.executable,'-B','-m','scripts.sqlite_offline_dispatch_guest_lab',
                             '--installer','--root',str(root)]+(['--partial'] if partial else []),stdout=subprocess.PIPE,
                            stderr=diagnostic,text=True)
    try:
        if not select.select([worker.stdout],[],[],20)[0]:
            raise RuntimeError('Fixture installer readiness timed out')
        expected='fixture_partial_ready' if partial else 'fixture_guards_ready'
        if worker.stdout.readline().strip()!=expected:
            raise RuntimeError('Fixture installer failed before readiness')
        before=dispatches(root,partial=partial)
        try:review_disposable_controller_recovery(root)
        except RuntimeError as error:
            if str(error)!='Controller lock held; recovery review refused':raise
        else:raise RuntimeError('Recovery review raced live controller')
        request=(root/'pending-request.json').read_bytes()
        worker.kill();worker.wait(timeout=10)
        if worker.returncode!=-signal.SIGKILL:
            raise RuntimeError('Real installer termination not established')
        after=dispatches(root,partial=partial)
        review=dispatch.review_disposable_offline_dispatch(root)
        guarded=sum(value=='guard_bytes_observed_mount_ownership_unverified'
                    for value in review['routes'].values())
        expected_guards=1 if partial else len(dispatch.ROUTES)
        if (guarded!=expected_guards or review['restoration_authorized'] is not False
                or review['blockers']!=['fixture_review_never_authorizes_restoration']):
            raise RuntimeError('Crash recovery review inconsistent with fixture')
        controller_review=review_disposable_controller_recovery(root)
        owned=sum(value=='request_bound_guard_mount_observed'
                  for value in controller_review['mount_evidence'].values())
        if (owned!=(0 if partial else len(dispatch.ROUTES))
                or controller_review['restoration_authorized'] is not False
                or (partial and controller_review['mount_evidence']['rc.docker']!='unreceipted_mount')):
            raise RuntimeError('Controller receipt recovery review inconsistent')
        try:
            with install_disposable_offline_dispatch(root):
                raise RuntimeError('Retained request unexpectedly adopted')
        except RuntimeError as error:
            if str(error)!='Retained request requires review; no reinstall':raise
        if (root/'pending-request.json').read_bytes()!=request:
            raise RuntimeError('Pending request changed after installer death')
        replacement_rejected=False
        if not partial:
            # Only this fake route: identical guard bytes with a new mount ID
            # must not inherit the dead controller's recorded ownership.
            target=root/'host'/dispatch.ROUTES['mover'][0]
            previous=dispatch._unique_mount_id(target)
            subprocess.run(['umount',str(target)],check=True,capture_output=True,timeout=10)
            subprocess.run(['mount','--bind',str(root/'deny-guard'),str(target)],
                           check=True,capture_output=True,timeout=10)
            subprocess.run(['mount','-o','remount,bind,ro,nosuid,nodev',str(target)],
                           check=True,capture_output=True,timeout=10)
            if dispatch._unique_mount_id(target)==previous:
                raise RuntimeError('Fixture replacement mount identity did not change')
            try:verify_disposable_offline_dispatch(root)
            except RuntimeError as error:
                if str(error)!='Owned guard mount changed; retain fence':raise
            else:raise RuntimeError('Equivalent replacement guard inherited ownership')
            changed=review_disposable_controller_recovery(root)
            if changed['mount_evidence']['mover']!='receipt_mount_conflict':
                raise RuntimeError('Recovery accepted replaced guard mount')
            replacement_rejected=True
        result=dict(status=('private_guest_partial_dispatch_crash_verified' if partial
                            else 'private_guest_offline_dispatch_crash_verified'),fixture_only=True,
                    partial_installation=partial,complete_binding_rejected=partial,
                    dispatches_denied_before_death=before,dispatches_denied_after_death=after,
                    installer_sigkill_verified=True,pending_request_unchanged=True,
                    recovery_review_guard_routes=guarded,restoration_authorized=False,
                    controller_receipt_mounts_observed=owned,live_controller_review_rejected=True,
                    identical_guard_replacement_rejected=replacement_rejected,
                    execution_environment=('dedicated_container' if socket.gethostname()=='mca-dispatch-fixture'
                                           else 'dedicated_vm'),
                    replacement_install_rejected=True,controller_death_removed_guards=False,
                    production_service_changes=False,
                    production_authorized=False,production_activation='disabled',
                    writer_exclusion_verified=False,restart_inhibition_verified=False)
        (root/'result.json').write_text(json.dumps(result,sort_keys=True))
        return result
    finally:
        if worker.poll() is None:worker.kill();worker.wait(timeout=10)
        worker.stdout.close();diagnostic.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True)
    parser.add_argument('--worker',action='store_true')
    parser.add_argument('--installer',action='store_true')
    parser.add_argument('--partial',action='store_true')
    args=parser.parse_args()
    require_dispatch_lab(args.root)
    if args.installer:
        if args.partial:
            real_command=dispatch.subprocess.run
            def pause_after_first_bind(command,**kwargs):
                result=real_command(command,**kwargs)
                if command[:2]==['mount','--bind']:
                    print('fixture_partial_ready',flush=True)
                    signal.pause()  # Parent kills this real installer here.
                    raise RuntimeError('Partial installer unexpectedly resumed')
                return result
            dispatch.subprocess.run=pause_after_first_bind
        with install_disposable_offline_dispatch(args.root):
            print('fixture_guards_ready',flush=True)
            signal.pause()
    elif args.worker:run(args.root,partial=args.partial)
    else:
        subprocess.run(['unshare','--mount','--propagation','private',sys.executable,'-B','-m',
            'scripts.sqlite_offline_dispatch_guest_lab','--worker','--root',args.root]
            +(['--partial'] if args.partial else []),
            check=True,timeout=120)
        # The private namespace is gone; original inert entries must remain.
        root=Path(args.root)
        request=json.loads((root/'pending-request.json').read_bytes())
        for name,original in request['originals'].items():
            content=(root/'host'/dispatch.ROUTES[name][0]).read_bytes()
            if hashlib.sha256(content).hexdigest()!=original['sha256']:
                raise RuntimeError('Underlying fixture original changed')
        result=json.loads((root/'result.json').read_text())
        result['underlying_originals_retained']=True
        (root/'result.json').write_text(json.dumps(result,sort_keys=True))
        print(json.dumps(result,sort_keys=True))
