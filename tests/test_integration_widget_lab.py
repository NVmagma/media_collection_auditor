"""Launcher policy through inert Docker stubs; no real container or network."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/integration_widget_lab.sh'
CID = 'a' * 64
TOKEN = 'disposable_fixture_token_01234567890123456789'


def run_lab(tmp_path, *, failure='', scenario='sample'):
    binary = tmp_path / 'bin'
    binary.mkdir()
    log = tmp_path / 'calls.jsonl'
    lab = tmp_path / 'lab'
    stub = '''
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['FIXTURE_LOG'], 'a') as handle:
    handle.write(json.dumps([name, *args]) + '\\n')
if name == 'mktemp':
    pathlib.Path(os.environ['FIXTURE_LAB']).mkdir()
    print(os.environ['FIXTURE_LAB'])
elif name == 'sleep':
    pass
elif args[0:2] == ['network', 'inspect']:
    if '.Driver' in args[-1]: print('bridge')
    else: print('false' if os.environ['FIXTURE_FAILURE'] == 'icc' else 'true')
elif args[0] == 'inspect':
    form = args[args.index('--format') + 1]
    if form == '{{.Image}}': print('sha256:' + 'd' * 64)
    elif 'Labels' in form: print('widget-api')
    elif 'IPAddress' in form: print('172.17.0.250')
    else: print('bridge')
elif args[0] == 'run':
    print('a' * 64 if '--detach' in args else os.environ['FIXTURE_TOKEN'])
elif args[0] == 'exec':
    sys.exit(1 if os.environ['FIXTURE_FAILURE'] == 'readiness' else 0)
elif args[0] == 'stop':
    assert args[-1] == 'a' * 64
else:
    sys.exit(7)
'''
    for name in ('docker', 'mktemp', 'sleep'):
        path = binary / name
        path.write_text('#!' + sys.executable + '\n' + stub)
        path.chmod(0o700)
    env = {**os.environ, 'PATH': str(binary) + os.pathsep + os.defpath,
           'FIXTURE_LOG': str(log), 'FIXTURE_LAB': str(lab), 'FIXTURE_FAILURE': failure,
           'FIXTURE_TOKEN': TOKEN}
    result = subprocess.run(['bash', str(SCRIPT), scenario], env=env,
                            capture_output=True, text=True, timeout=20)
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    return result, calls, lab


@pytest.mark.parametrize('scenario', ['sample', 'empty', 'unavailable'])
def test_only_new_fixture_gets_run_exec_and_private_mounts(tmp_path, scenario):
    result, calls, lab = run_lab(tmp_path, scenario=scenario)
    assert result.returncode == 0, result.stderr
    docker = [c[1:] for c in calls if c[0] == 'docker']
    runs = [c for c in docker if c[0] == 'run']
    assert len(runs) == 2
    for args in runs:
        assert '--pull=never' in args and '--read-only' in args
        assert '--cap-drop' in args and args[args.index('--cap-drop') + 1] == 'ALL'
        assert '--privileged' not in args and '--publish' not in args and '-p' not in args
    server = next(c for c in runs if '--detach' in c)
    assert server[server.index('--network') + 1] == 'bridge'
    assert '--restart=no' in server and '--lifetime-seconds' in server
    mounts = [server[i + 1] for i, value in enumerate(server[:-1]) if value == '--mount']
    assert len(mounts) == 2 and all(m.endswith(',readonly') for m in mounts)
    assert not any('docker.sock' in m or '/media' in m.split('target=')[-1] for m in mounts)
    assert all(c[1] == CID for c in docker if c[0] == 'exec')
    assert not any(c[0] == 'stop' for c in docker)
    assert 'fixture_url=http://172.17.0.250:8080' in result.stdout
    assert TOKEN not in result.stdout + result.stderr
    assert (lab / 'token').stat().st_mode & 0o777 == 0o600


def test_disabled_bridge_communication_refuses_before_creation(tmp_path):
    result, calls, lab = run_lab(tmp_path, failure='icc')
    assert result.returncode == 2
    assert not lab.exists()
    assert not any(c[0] == 'docker' and c[1] in ('run', 'exec', 'stop') for c in calls)


def test_failed_readiness_stops_only_new_labeled_container(tmp_path):
    result, calls, _ = run_lab(tmp_path, failure='readiness')
    assert result.returncode == 2
    stops = [c for c in calls if c[:2] == ['docker', 'stop']]
    assert stops == [['docker', 'stop', '--time', '5', CID]]
    assert TOKEN not in result.stdout + result.stderr
