"""Launcher policy through inert Docker/timeout stubs; no actual services."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/sqlite_jellyfin_readonly_lab.sh'
CID = 'a' * 64


def run_lab(tmp_path, failure=''):
    binary = tmp_path / 'bin'
    binary.mkdir()
    log = tmp_path / 'calls.jsonl'
    state = tmp_path / 'docker-label'
    stub = '''
import json, os, pathlib, subprocess, sys
name=pathlib.Path(sys.argv[0]).name
args=sys.argv[1:]
if name=='uname': print('Linux'); sys.exit(0)
if name=='readlink': print(pathlib.Path(args[-1]).resolve()); sys.exit(0)
if name=='timeout':
    args=args[1:] if args[0].startswith('--kill-after=') else args
    sys.exit(subprocess.run(args[1:]).returncode)
with open(os.environ['LAB_LOG'],'a') as handle: handle.write(json.dumps(args)+'\\n')
if args[:2]==['image','inspect']: pass
elif args[0]=='inspect':
    form=args[args.index('--format')+1]
    if form=='{{.Image}}': print('sha256:'+'d'*64)
    elif form=='{{.Config.Image}}': print('jellyfin/jellyfin:cached')
    elif 'Labels' in form: print('changed' if os.environ['LAB_FAILURE']=='identity' else pathlib.Path(os.environ['LAB_STATE']).read_text())
    else: print('none true false '+('true' if os.environ['LAB_FAILURE']=='writable' else 'false'))
elif args[0]=='create':
    label=args[args.index('--label')+1].split('=',1)[1]
    pathlib.Path(os.environ['LAB_STATE']).write_text(label)
    print('a'*64)
elif args[0]=='run':
    if '--phase' in args:
        phase=args[args.index('--phase')+1]
        if phase==os.environ['LAB_FAILURE']: sys.exit(2)
        print(json.dumps({'status':'fixture_test_stub','phase':phase}))
elif args[0] in ('start','restart','rm'):
    if args[0]=='rm' and os.environ['LAB_FAILURE']=='cleanup': sys.exit(1)
    assert args[-1]=='a'*64, 'Existing service targeted'
else: sys.exit(7)
'''
    for name in ('docker', 'timeout', 'uname', 'readlink'):
        path = binary / name
        path.write_text('#!' + sys.executable + '\n' + stub)
        path.chmod(0o700)
    env = dict(os.environ, PATH=str(binary) + os.pathsep + os.defpath,
               LAB_LOG=str(log), LAB_STATE=str(state), LAB_FAILURE=failure)
    result = subprocess.run(['bash', str(SCRIPT), str(tmp_path)], capture_output=True,
                            text=True, timeout=20, env=env)
    return result, [json.loads(line) for line in log.read_text().splitlines()]


def test_only_new_label_bound_server_has_lifecycle_controls(tmp_path):
    result, calls = run_lab(tmp_path)
    assert result.returncode == 0, result.stderr
    assert 'isolated_real_jellyfin_readonly_complete' in result.stdout
    controls = [call for call in calls if call[0] in ('start', 'restart', 'rm')]
    assert [call[0] for call in controls] == ['start', 'restart', 'rm']
    assert all(call[-1] == CID for call in controls)
    create = next(call for call in calls if call[0] == 'create')
    assert create[create.index('--network') + 1] == 'none'
    assert '--read-only' in create and '--cap-drop' in create
    assert '--privileged' not in create and '-p' not in create and '--publish' not in create
    assert '--entrypoint' in create and '/usr/bin/timeout' in create and '300s' in create
    mounts = [create[i+1] for i, value in enumerate(create[:-1]) if value == '--mount']
    assert len(mounts) == 2
    assert any('dst=/media,readonly' in mount for mount in mounts)
    assert all(str(tmp_path) in mount for mount in mounts)
    clients = [call for call in calls if call[0] == 'run' and '--phase' in call]
    assert [call[-1] for call in clients] == ['prepare', 'setup', 'check']
    for call in clients[1:]:
        assert call[call.index('--network')+1] == 'container:' + CID
    assert not any('/var/run/docker.sock' in ' '.join(call) for call in calls)
    assert not any(call[0] == 'pull' for call in calls)


@pytest.mark.parametrize('failure', ['setup', 'check', 'writable', 'identity', 'cleanup'])
def test_failure_never_restarts_existing_service_or_reports_success(tmp_path, failure):
    result, calls = run_lab(tmp_path, failure)
    assert result.returncode != 0
    assert 'isolated_real_jellyfin_readonly_complete' not in result.stdout
    assert all(call[-1] == CID for call in calls if call[0] in ('start', 'restart', 'rm'))
    if failure in ('setup', 'writable', 'identity'):
        assert not any(call[0] == 'restart' for call in calls)
    if failure == 'identity':
        assert not any(call[0] == 'rm' for call in calls)
