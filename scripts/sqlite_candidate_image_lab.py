"""Test a sealed candidate image; no publish, host mounts, ports or deployment."""
import argparse
import json
from pathlib import Path
import re
import subprocess


def command(*args, **kwargs):
    result = subprocess.run(args, capture_output=True, timeout=180, **kwargs)
    if result.returncode:
        raise RuntimeError('Candidate fixture command failed: ' + result.stderr.decode(errors='replace')[-2000:])
    return result.stdout


PROBE = r'''
import importlib, json, os, subprocess, sys, time, urllib.request, urllib.error
from pathlib import Path
for name in ('sqlite_scheduled_service', 'sqlite_scheduled_production', 'sqlite_tracking_view',
             'sqlite_scheduled_observations', 'sqlite_arr_completion', 'sqlite_scheduled_arr_delivery'):
    module = importlib.import_module('app.' + name)
    assert Path(module.__file__).is_relative_to('/app/app'), 'Image application modules required'
state = Path('/tmp/state.json')
raw = b'{"first_seen":{"Fixture":"2024-01-01T00:00:00"},"queued":{},"in_removal":{},"keep_seen":{},"arr_sync_pending":{}}'
state.write_bytes(raw)
url = 'http://127.0.0.1:8080/api/v1/summary'
def fetch(token=None):
    headers = {'Authorization': 'Bearer ' + token} if token else {}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=1) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        with error: return error.code, json.loads(error.read())
for _ in range(100):
    try:
        code, _ = fetch()
        if code == 401: break
    except (OSError, urllib.error.URLError): pass
    time.sleep(.1)
else: raise RuntimeError('Candidate entrypoint did not serve private API')
code, report = fetch(os.environ['INTEGRATION_API_TOKEN'])
assert code == 200 and report['tracking_counts']['waiting'] == 1
assert report['storage_authority'] == 'json' and report['freshness_verified'] is False
# Actual production entrypoint must refuse SQLite before starting a worker/web thread.
env = dict(os.environ, AUDITOR_STATE_BACKEND='sqlite', READ_ONLY_API_SERVICE='false')
child = subprocess.run([sys.executable, '-B', '-m', 'app.main'], env=env,
                       capture_output=True, timeout=15)
assert child.returncode != 0 and b'SQLite production activation is disabled' in child.stderr
assert state.read_bytes() == raw
print(json.dumps({'status':'candidate_entrypoint_verified','unauthenticated_status':401,
    'authenticated_status':200,'sqlite_entrypoint_refused':True,'json_bytes_unchanged':True}))
'''

FIXTURES = r'''
import io, os, subprocess, sys, tarfile
from pathlib import Path
target = Path('/tmp/candidate-fixtures'); target.mkdir()
tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read()),mode='r:').extractall(target,filter='data')
os.chdir(target)
os.environ['PYTHONPATH'] = str(target) + ':/app:/app/app'
os.environ['TMPDIR'] = '/tmp'
preflight = subprocess.run([sys.executable,'-B',str(target/'scripts/sqlite_release_preflight.py')],
    capture_output=True,check=True,timeout=15)
import json
observed = json.loads(preflight.stdout)
assert observed['read_only'] is True and observed['source_snapshot_validated'] is False
assert observed['source_json']['counts']['first_seen'] == 1
assert observed['production_authorized'] is False
print(json.dumps({'status':'read_only_release_preflight_verified'}))
for module in ('scripts.sqlite_coordinator_fixture','scripts.sqlite_scheduled_arr_fixture',
               'scripts.sqlite_scheduled_preview_fixture',
               'scripts.sqlite_release_preparation_fixture',
               'scripts.sqlite_release_recovery_fixture',
               'scripts.sqlite_tv_compatibility_fixture','scripts.sqlite_restore_fixture',
               'scripts.sqlite_scheduled_transport_fixture'):
    subprocess.run([sys.executable,'-S','-B','-m',module],check=True,timeout=120)
'''


def run(*, image, source_revision, checkout):
    if not isinstance(image, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', image):
        raise ValueError('Full cached candidate image ID required')
    if not isinstance(source_revision, str) or not re.fullmatch(r'[0-9a-f]{40}', source_revision):
        raise ValueError('Exact candidate source revision required')
    metadata = json.loads(command('docker', 'image', 'inspect', image))
    if len(metadata) != 1 or metadata[0]['Id'] != image:
        raise RuntimeError('Candidate identity mismatch')
    config = metadata[0]['Config']
    labels = config.get('Labels') or {}
    if (config.get('StopSignal') != 'SIGINT' or config.get('Volumes') or config.get('Entrypoint') != ['python', '-m', 'app.main']
            or labels.get('org.opencontainers.image.revision') != source_revision
            or labels.get('io.media-collection-auditor.sqlite-activation') != 'disabled'):
        raise RuntimeError('Sealed candidate metadata required')
    # Only committed fixture scripts enter the test container; app comes from image.
    archive = command('git', '-C', str(checkout), 'archive', '--format=tar', source_revision, 'scripts')
    container = command('docker', 'create', '--pull=never', '--network', 'none', '--read-only',
        '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--pids-limit', '64',
        '--memory', '256m', '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=128m',
        '--env', 'READ_ONLY_API_SERVICE=true', '--env', 'STATE_FILE=/tmp/state.json',
        '--env', 'WEB_PORT=8080', '--env', 'WEB_SESSION_SECRET=disposable-image-fixture-secret',
        '--env', 'INTEGRATION_API_TOKEN=disposable_candidate_image_token_0123456789', image).decode().strip()
    if not re.fullmatch(r'[0-9a-f]{64}', container):
        raise RuntimeError('New fixture container identity required')
    try:
        command('docker', 'start', container)
        print(command('docker', 'exec', container, 'python', '-B', '-c', PROBE).decode(), end='')
        print(command('docker', 'exec', '--interactive', container, 'python', '-B', '-c', FIXTURES,
                      input=archive).decode(), end='')
        command('docker', 'stop', '--time', '5', container)
        state = json.loads(command('docker', 'inspect', '--format', '{{json .State}}', container))
        if state['Running'] or state['OOMKilled'] or state['ExitCode'] not in (0, 143):
            raise RuntimeError('Candidate fixture did not stop cleanly')
    finally:
        command('docker', 'rm', '--force', container)
    return {'status': 'candidate_image_acceptance_complete', 'image_id': image,
        'source_revision': source_revision, 'fixture_only': True, 'host_mounts': False,
        'published_ports': False, 'registry_push_performed': False,
        'production_activation': 'disabled', 'production_authorized': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--source-revision', required=True)
    args = parser.parse_args()
    print(json.dumps(run(image=args.image, source_revision=args.source_revision,
        checkout=Path(__file__).resolve().parents[1])))
