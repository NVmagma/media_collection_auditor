"""Packaged controller death acceptance in a dedicated, new local container only."""
import argparse
import json
import os
from pathlib import Path
import select
import signal
import socket
import subprocess
import sys

from scripts.sqlite_host_controller_bundle import build


def run(root):
    root=Path(root)
    if (sys.platform!='linux' or socket.gethostname()!='mca-host-controller-fixture'
            or not Path('/.dockerenv').is_file() or root.parent!=Path('/fixture')
            or root.resolve()!=root):
        raise RuntimeError('Dedicated controller container fixture required')
    bundle=root.with_name(root.name+'-bundle')
    build(bundle)
    base=[sys.executable,'-I','-S','-B',str(bundle/'controller.py')]
    worker=subprocess.Popen([*base,'prepare','--root',str(root),'--hold'],stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,text=True)
    try:
        if not select.select([worker.stdout],[],[],20)[0]:raise RuntimeError('Controller readiness timeout')
        ready=worker.stdout.readline()
        if not ready:raise RuntimeError('Controller failed: '+worker.stderr.read()[-2000:])
        report=json.loads(ready)
        if report['status']!='blocked' or report['external_actions_authorized'] is not False:
            raise RuntimeError('Preparation unexpectedly authorized action')
        competing=subprocess.run([*base,'review','--root',str(root)],capture_output=True,timeout=15)
        if competing.returncode==0 or b'Live controller lock held' not in competing.stderr:
            raise RuntimeError('Review did not reject live controller')
        before={path.name:path.read_bytes() for path in root.iterdir()}
        worker.kill();worker.wait(timeout=10)
        if worker.returncode!=-signal.SIGKILL:raise RuntimeError('Real controller SIGKILL not observed')
        reviewed=subprocess.run([*base,'review','--root',str(root)],check=True,capture_output=True,timeout=15)
        review=json.loads(reviewed.stdout)
        if (review['scope_matches']['controller_session'] is not False
                or not all(value for key,value in review['scope_matches'].items() if key!='controller_session')
                or review['controller_adoption_authorized'] is not False
                or review['external_actions_authorized'] is not False):
            raise RuntimeError('Replacement controller inherited authority')
        replacement=subprocess.run([*base,'prepare','--root',str(root)],capture_output=True,timeout=15)
        if replacement.returncode==0:raise RuntimeError('Retained request adopted')
        if {path.name:path.read_bytes() for path in root.iterdir()}!=before:
            raise RuntimeError('Controller evidence changed')
        return dict(status='host_preparation_controller_crash_complete',fixture_only=True,
                    actual_sigkill_verified=True,live_lock_conflict_verified=True,
                    retained_request_unchanged=True,replacement_session_rejected=True,
                    stdlib_only_bundle_verified=True,python_version=sys.version.split()[0],
                    production_authorized=False,production_activation='disabled',
                    writer_exclusion_verified=False,external_actions_authorized=False,
                    restoration_authorized=False)
    finally:
        if worker.poll() is None:worker.kill();worker.wait(timeout=10)
        worker.stdout.close();worker.stderr.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True)
    print(json.dumps(run(parser.parse_args().root),sort_keys=True))
