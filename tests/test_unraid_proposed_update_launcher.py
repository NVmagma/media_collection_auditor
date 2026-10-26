"""Exercise actual Bash mount gate with synthetic Docker output, no daemon."""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/unraid_proposed_update_review.sh'
IMAGE = 'sha256:' + 'a' * 64
DOCKER = '''#!PYTHON
import json, os, sys
args = sys.argv[1:]
with open(os.environ['CALL_LOG'], 'a') as stream:
    stream.write(json.dumps(args) + '\\n')
if args[:2] == ['image', 'inspect']:
    if '--format' in args:
        print('null' if 'Volumes' in args[args.index('--format') + 1] else os.environ['FIXTURE_IMAGE'])
    else:
        print('[{"Id": "fixture"}]')
elif args[0] == 'inspect':
    if '--format' in args:
        # Docker prints its own newline after the range's final printf newline.
        sys.stdout.write(os.environ['MOUNT_OUTPUT'])
    else:
        print('[{"Name": "/media_collection_auditor"}]')
elif args[0] == 'run':
    payload = json.load(sys.stdin)
    assert len(payload['containers']) == len(payload['images']) == 1
    assert args[args.index('--network')+1] == 'none'
    assert '--read-only' in args and '--pull=never' in args
    assert args[args.index('--volumes-from')+1] == 'media_collection_auditor:ro'
    assert not any('docker.sock' in arg or arg.startswith('--publish') for arg in args)
    print('{"status": "fixture_helper_reached", "update_authorized": false}')
else:
    raise SystemExit(90)
'''


def run_launcher(tmp_path, mounts):
    binary = tmp_path / 'docker'; binary.write_text(DOCKER.replace('PYTHON', sys.executable, 1)); binary.chmod(0o755)
    log = tmp_path / 'calls'
    result = subprocess.run(['bash', str(SCRIPT), IMAGE], text=True, capture_output=True,
        env={**os.environ, 'PATH': str(tmp_path)+os.pathsep+os.environ['PATH'], 'CALL_LOG': str(log),
             'FIXTURE_IMAGE': IMAGE, 'MOUNT_OUTPUT': mounts})
    return result, [json.loads(line) for line in log.read_text().splitlines()]


def test_docker_extra_newline_does_not_reject_correct_mounts(tmp_path):
    result, calls = run_launcher(tmp_path, 'bind /media\nbind /sqlite-control\nbind /app/logs\n\n')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['status'] == 'fixture_helper_reached'
    assert sum(call[0] == 'run' for call in calls) == 1


@pytest.mark.parametrize('mounts', [
    'bind /media\nbind /app/logs\n\n',
    'bind /media\nbind /app/logs\nbind /sqlite-control\nbind /docker.sock\n\n',
    'volume /media\nbind /app/logs\nbind /sqlite-control\n\n',
    'bind /media\nbind /app/logs\nbind /sqlite-control\nbind /media\n\n',
])
def test_unknown_missing_volume_or_duplicate_mount_stops_before_helper(tmp_path, mounts):
    result, calls = run_launcher(tmp_path, mounts)
    assert result.returncode == 2
    assert not any(call[0] == 'run' for call in calls)
