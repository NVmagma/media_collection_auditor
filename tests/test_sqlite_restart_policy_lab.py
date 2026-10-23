"""Exercise launcher failure paths using an inert Docker command, never a daemon."""
import json
import os
from pathlib import Path
import subprocess

import pytest

LAUNCHER = Path(__file__).parents[1] / "scripts/sqlite_restart_policy_lab.sh"
FAKE = '''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
state_path = pathlib.Path(os.environ['FAKE_STATE'])
s = json.loads(state_path.read_text()) if state_path.exists() else {'policy':'on-failure','running':True,'restarts':0,'exit':0}
mode = os.environ.get('FAIL_MODE', '')
if args[:2] == ['image','inspect']:
    sys.exit(0)
if args[0] == 'create':
    s['label'] = args[args.index('--label')+1].split('=',1)[1]
    mount = next(a for a in args if a.startswith('type=bind,src=') and a.endswith(',dst=/fixture'))
    s['lab'] = mount.split('src=',1)[1].split(',dst=',1)[0]
    state_path.write_text(json.dumps(s))
    print('a'*64)
    sys.exit(0)
assert args[-1] == 'a'*64, 'Only new ID allowed'
lab = pathlib.Path(s['lab'])
if args[0] == 'start':
    (lab/'starts').write_text('1')
elif args[0] == 'update':
    if mode == 'update': sys.exit(1)
    s['policy']='no'
elif args[0] == 'rm':
    if mode == 'cleanup': sys.exit(1)
    s['removed']=True
elif args[0] == 'inspect':
    if (lab/'crash.1').exists() and s['restarts']==0 and mode != 'baseline':
        (lab/'starts').write_text('2')
        s['restarts']=1
    if (lab/'crash.2').exists():
        s['running']=False
        s['exit']=17
    fmt=args[args.index('--format')+1]
    if 'Labels' in fmt:
        print('changed' if mode=='identity' and s['policy']=='no' else s['label'])
    elif 'HostConfig' in fmt and 'State' not in fmt:
        print(s['policy'])
    elif 'State.ExitCode' in fmt:
        print(str(s['running']).lower(), s['exit'], s['restarts'], s['policy'])
    elif 'State.Running' in fmt:
        print(str(s['running']).lower())
    elif 'RestartCount' in fmt:
        print(s['restarts'])
    else: raise AssertionError(fmt)
else: raise AssertionError(args)
state_path.write_text(json.dumps(s))
'''


@pytest.mark.parametrize("failure", ["", "update", "identity", "cleanup", "baseline"])
def test_launcher_requires_baseline_policy_identity_and_cleanup(tmp_path, failure):
    commands = tmp_path / "bin"
    commands.mkdir()
    docker = commands / "docker"
    docker.write_text(FAKE)
    docker.chmod(0o755)
    # Preserve a live controller to kill, accelerate observation waits only.
    sleep = commands / "sleep"
    sleep.write_text("""#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys, time
if sys.argv[1] == '60':
    os.execv('/bin/sleep', ['sleep', '60'])
p = pathlib.Path(os.environ['FAKE_STATE'])
if p.exists():
    s = json.loads(p.read_text())
    lab = pathlib.Path(s['lab'])
    if (lab/'crash.1').exists() and (lab/'starts').read_text() == '1':
        subprocess.run(['docker','inspect','--format','{{.RestartCount}}','a'*64], stdout=subprocess.DEVNULL, check=True)
time.sleep(0.001)
""")
    sleep.chmod(0o755)
    uname = commands / "uname"
    uname.write_text('#!/bin/sh\necho Linux\n')
    uname.chmod(0o755)
    readlink = commands / "readlink"
    readlink.write_text('#!/bin/sh\n[ "$1" = -f ] && shift\nprintf "%s\\n" "$1"\n')
    readlink.chmod(0o755)
    timeout = commands / "timeout"
    timeout.write_text('#!/bin/sh\ncase "$1" in --kill-after=*) shift;; esac\nshift\nexec "$@"\n')
    timeout.chmod(0o755)
    parent = tmp_path / "labs"
    parent.mkdir()
    state = tmp_path / "docker-state.json"
    env = dict(os.environ, PATH=str(commands)+os.pathsep+os.environ['PATH'],
               FAKE_STATE=str(state), FAIL_MODE=failure)
    result = subprocess.run(['bash', str(LAUNCHER), str(parent)], env=env,
                            capture_output=True, text=True, timeout=120)
    observed = json.loads(state.read_text())
    if not failure:
        assert result.returncode == 0, result.stderr
        assert 'status=isolated_restart_policy_complete' in result.stdout
        assert observed['removed'] is True
        assert observed['policy'] == 'no'
    else:
        assert result.returncode != 0
        assert 'status=isolated_restart_policy_complete' not in result.stdout
        if failure == 'identity':
            assert not observed.get('removed', False)
