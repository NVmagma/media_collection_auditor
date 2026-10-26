"""Rehearse native loader entry in the dedicated controller container only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import select
import shutil
import signal
import socket
import subprocess
import sys
import sysconfig

from scripts.sqlite_host_controller_bundle import build


def run(root):
    root=Path(root)
    if (sys.platform!='linux' or socket.gethostname()!='mca-host-controller-fixture'
            or not Path('/.dockerenv').is_file() or root.parent!=Path('/fixture') or root.resolve()!=root):
        raise RuntimeError('Dedicated native controller container required')
    runtime=root.with_name(root.name+'-runtime');runtime.mkdir(mode=0o700)
    (runtime/'.disposable_controller_runtime').write_bytes(b'DISPOSABLE CONTROLLER RUNTIME ONLY\n')
    fs=runtime/'rootfs';(fs/'usr/local/bin').mkdir(parents=True)
    # Mirror only this cached image's interpreter/stdlib/native libraries. This
    # fixture does not read host mounts or repackage site packages.
    executable=fs/'usr/local/bin'/Path(sys.executable).resolve().name
    shutil.copy2(Path(sys.executable).resolve(),executable)
    (fs/'usr/local/bin/python3').symlink_to(executable.name)
    stdlib=Path(sysconfig.get_path('stdlib'))
    shutil.copytree(stdlib,fs/'usr/local/lib'/stdlib.name,
                    ignore=shutil.ignore_patterns('site-packages','__pycache__','test','tests'))
    for path in Path('/usr/local/lib').glob('libpython*.so*'):
        shutil.copy2(path,fs/'usr/local/lib'/path.name,follow_symlinks=True)
    machine=platform.machine()
    if machine=='aarch64':triplet='aarch64-linux-gnu';loader='/lib/ld-linux-aarch64.so.1'
    elif machine=='x86_64':triplet='x86_64-linux-gnu';loader='/lib64/ld-linux-x86-64.so.2'
    else:raise RuntimeError('Unsupported fixture architecture')
    shutil.copytree(Path('/lib')/triplet,fs/'lib'/triplet,symlinks=False)
    (fs/'usr/lib').mkdir(parents=True)
    (fs/'usr/lib'/triplet).symlink_to('../../lib/'+triplet)
    destination=fs/loader.lstrip('/');destination.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(Path(loader).resolve(),destination)
    bundle=root.with_name(root.name+'-bundle')
    prepared=build(bundle)
    launcher=Path(__file__).with_name('sqlite_host_controller_native.sh')
    base=['/bin/bash','-p',str(launcher)]
    tail=[str(runtime),str(bundle),str(root),prepared['bundle_manifest_sha256'],prepared['entrypoint_sha256']]
    worker=subprocess.Popen([*base,'hold',*tail],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        if not select.select([worker.stdout],[],[],30)[0]:raise RuntimeError('Native controller readiness timeout')
        line=worker.stdout.readline()
        if not line:raise RuntimeError('Native launch failed: '+worker.stderr.read()[-3000:])
        ready=json.loads(line)
        if ready['external_actions_authorized'] is not False:raise RuntimeError('Unexpected authorization')
        # The real interpreter/loader and all mapped extension libraries must
        # come from this runtime copy, not fall back to the container image.
        maps=Path('/proc')/str(worker.pid)/'maps'
        loaded=[row.split()[-1] for row in maps.read_text().splitlines()
                if len(row.split())>=6 and row.split()[-1].startswith('/')]
        if not loaded or any(not name.startswith(str(fs)+'/') for name in loaded):
            raise RuntimeError('Native fixture loaded external paths: '+repr(sorted(set(name for name in loaded if not name.startswith(str(fs)+'/')))))
        before={path.name:path.read_bytes() for path in root.iterdir()}
        worker.kill();worker.wait(timeout=10)
        if worker.returncode!=-signal.SIGKILL:raise RuntimeError('Native controller SIGKILL not observed')
        reviewed=subprocess.run([*base,'review',*tail],check=True,capture_output=True,timeout=20)
        report=json.loads(reviewed.stdout)
        if report['scope_matches']['controller_session'] or report['controller_adoption_authorized']:
            raise RuntimeError('Native replacement inherited controller authority')
        if {path.name:path.read_bytes() for path in root.iterdir()}!=before:
            raise RuntimeError('Native controller evidence changed')
        bad_tail=[*tail[:-2],'0'*64,tail[-1]]
        rejected=subprocess.run([*base,'review',*bad_tail],capture_output=True,timeout=20)
        if rejected.returncode==0:raise RuntimeError('Unreviewed bundle manifest accepted')
        stdlib_copy=fs/'usr/local/lib'/stdlib.name
        retained_stdlib=stdlib_copy.with_name(stdlib_copy.name+'-retained')
        stdlib_copy.rename(retained_stdlib)
        new_control=root.with_name(root.name+'-incomplete-runtime')
        missing_tail=[tail[0],tail[1],str(new_control),*tail[3:]]
        try:
            incomplete=subprocess.run([*base,'prepare',*missing_tail],capture_output=True,timeout=20)
            if incomplete.returncode==0 or new_control.exists():
                raise RuntimeError('Incomplete runtime created control state')
        finally:retained_stdlib.rename(stdlib_copy)
        return dict(status='native_host_preparation_launcher_fixture_complete',fixture_only=True,
                    actual_sigkill_verified=True,retained_request_unchanged=True,
                    replacement_session_rejected=True,exported_runtime_mapping_verified=True,
                    altered_manifest_rejected=True,incomplete_runtime_rejected_before_state=True,architecture=machine,
                    production_authorized=False,production_activation='disabled',
                    external_actions_authorized=False,writer_exclusion_verified=False)
    finally:
        if worker.poll() is None:worker.kill();worker.wait(timeout=10)
        worker.stdout.close();worker.stderr.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True)
    print(json.dumps(run(parser.parse_args().root),sort_keys=True))
