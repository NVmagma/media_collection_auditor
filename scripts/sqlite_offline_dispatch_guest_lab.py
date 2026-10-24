"""Guard only fake host paths in the separate VM; kill the installer, not services."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys

from app import sqlite_disposable_offline_dispatch as dispatch
from app.sqlite_disposable_offline_dispatch import (
    GUARD, MARKER, install_disposable_offline_dispatch, verify_disposable_offline_dispatch,
)
from scripts.sqlite_nfs4_guest_lab import require_guest


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
    require_guest()
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
        request=(root/'pending-request.json').read_bytes()
        worker.kill();worker.wait(timeout=10)
        if worker.returncode!=-signal.SIGKILL:
            raise RuntimeError('Real installer termination not established')
        after=dispatches(root,partial=partial)
        try:
            with install_disposable_offline_dispatch(root):
                raise RuntimeError('Retained request unexpectedly adopted')
        except RuntimeError as error:
            if str(error)!='Retained request requires review; no reinstall':raise
        if (root/'pending-request.json').read_bytes()!=request:
            raise RuntimeError('Pending request changed after installer death')
        result=dict(status=('private_guest_partial_dispatch_crash_verified' if partial
                            else 'private_guest_offline_dispatch_crash_verified'),fixture_only=True,
                    partial_installation=partial,complete_binding_rejected=partial,
                    dispatches_denied_before_death=before,dispatches_denied_after_death=after,
                    installer_sigkill_verified=True,pending_request_unchanged=True,
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
    require_guest()
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
