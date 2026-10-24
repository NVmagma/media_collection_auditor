"""Run actual scheduled rename fixtures in one new cached-image Linux container.

No host mounts, network, service access, added capabilities, pulls or builds.
"""
import argparse
import json
from pathlib import Path
import re

from scripts.sqlite_offline_dispatch_container_lab import command, source_archive


def run(image, *, gate7=False, worker=False, routed=False, slot=False, configured=False, layout=False, runtime=False, tracking=False, arr_queue=False, arr_delivery=False, arr_completion=False, scheduled_arr=False):
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', image):
        raise ValueError('Full cached image ID required')
    metadata = json.loads(command('docker', 'image', 'inspect', image))
    if len(metadata) != 1 or metadata[0]['Id'] != image or metadata[0]['Config'].get('Volumes'):
        raise RuntimeError('Exact cached image without declared volumes required')
    fixtures = (['scripts.sqlite_scheduled_gate7_fixture'] if gate7 else []) + [
        'scripts.sqlite_scheduled_move_fixture', 'scripts.sqlite_scheduled_transport_fixture']
    if worker:
        fixtures[0:0] = ['scripts.sqlite_scheduled_worker_fixture', 'scripts.sqlite_scheduled_checkpoint_fixture']
    if routed:
        fixtures.insert(0, 'scripts.sqlite_scheduled_routed_fixture')
    if slot:
        fixtures.insert(0, 'scripts.sqlite_scheduled_routed_slot_fixture')
    if configured:
        fixtures.insert(0, 'scripts.sqlite_scheduled_configured_slot_fixture')
    if layout:
        fixtures.insert(0, 'scripts.sqlite_scheduled_worker_layout_fixture')
    if runtime:
        fixtures.insert(0, 'scripts.sqlite_scheduled_runtime_fixture')
    if tracking:
        fixtures.insert(0, 'scripts.sqlite_tracking_view_fixture')
    if arr_queue:
        fixtures.insert(0, 'scripts.sqlite_arr_queue_fixture')
    if arr_delivery:
        fixtures.insert(0, 'scripts.sqlite_arr_delivery_fixture')
    if arr_completion:
        fixtures.insert(0, 'scripts.sqlite_arr_completion_fixture')
    if scheduled_arr:
        fixtures.insert(0, 'scripts.sqlite_scheduled_arr_fixture')
    source = source_archive(Path(__file__).resolve().parents[1])
    container = command('docker', 'create', '--pull=never', '--network', 'none',
        '--user', '0:0', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
        '--pids-limit', '64', '--memory', '256m', '--tmpfs', '/fixture:rw,noexec,nosuid,nodev,size=64m',
        '--env', 'TMPDIR=/fixture', '--interactive', '--workdir', '/fixture',
        '--entrypoint', '/usr/local/bin/python3', image, '-I', '-S', '-B', '-c',
        'import sys,tarfile,io,os,subprocess; '
        'tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read()),mode="r:").extractall("/fixture/code",filter="data"); '
        'os.chdir("/fixture/code"); '
        '[subprocess.run([sys.executable,"-S","-B","-m",module],check=True,timeout=180) for module in '+repr(fixtures)+']'
        ).decode().strip()
    if not re.fullmatch(r'[0-9a-f]{64}', container):
        raise RuntimeError('Full newly created container ID required')
    try:
        output = command('docker', 'start', '--attach', '--interactive', container, input=source).decode()
        state = json.loads(command('docker', 'inspect', '--format', '{{json .State}}', container))
        if state['ExitCode'] != 0 or state['OOMKilled']:
            raise RuntimeError('Scheduled move fixture failed')
        return output
    finally:
        command('docker', 'rm', '--force', container)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--gate7', action='store_true')
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--routed', action='store_true')
    parser.add_argument('--slot', action='store_true')
    parser.add_argument('--configured', action='store_true')
    parser.add_argument('--layout', action='store_true')
    parser.add_argument('--runtime', action='store_true')
    parser.add_argument('--tracking', action='store_true')
    parser.add_argument('--arr-queue', action='store_true')
    parser.add_argument('--arr-delivery', action='store_true')
    parser.add_argument('--arr-completion', action='store_true')
    parser.add_argument('--scheduled-arr', action='store_true')
    args = parser.parse_args()
    print(run(args.image, gate7=args.gate7, worker=args.worker, routed=args.routed, slot=args.slot, configured=args.configured, layout=args.layout, runtime=args.runtime, tracking=args.tracking, arr_queue=args.arr_queue, arr_delivery=args.arr_delivery, arr_completion=args.arr_completion, scheduled_arr=args.scheduled_arr), end='')
