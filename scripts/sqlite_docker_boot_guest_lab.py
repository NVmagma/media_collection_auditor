"""Guest-only boot continuity rehearsal. Never install these units on Tower.

Uses a previously stopped synthetic writer, not production Docker configuration.
The separate VM and its private disk are the isolation boundary.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

from app.sqlite_docker_maintenance_hold import held_disposable_hold
from app.sqlite_docker_writer_observation import require_stopped_writer
from scripts.sqlite_docker_writer_guest_lab import Client
from scripts.sqlite_nfs4_guest_lab import require_guest

PREFIX = 'mca-disposable-boot'


def safe_path(value):
    path = Path(value)
    if (not path.is_absolute() or path.resolve() != path
            or not re.fullmatch(r'/[A-Za-z0-9_./-]+', str(path))):
        raise ValueError('Canonical unit-safe guest path required')
    return path


def units(root, source, binaries):
    root, source, binaries = map(safe_path, (root, source, binaries))
    policy = PREFIX + '-policy.service'
    common = f'WorkingDirectory={source}\nRestart=no\nTimeoutStopSec=30\n'
    return {
        policy: '[Unit]\nDescription=Disposable deny-only boot policy\n'
            '[Service]\nType=exec\n' + common +
            f'ExecStart=/usr/bin/python3 -B -m scripts.sqlite_docker_authorization_fixture --root {root}/control --resume-fixture\n',
        PREFIX + '-engine.service': '[Unit]\nDescription=Disposable fenced guest engine\n'
            f'BindsTo={policy}\nAfter={policy}\n'
            '[Service]\nType=exec\n' + common +
            f'Environment=PATH={binaries}:/usr/sbin:/usr/bin:/sbin:/bin\n'
            f'ExecStartPre=/usr/bin/python3 -B -m scripts.sqlite_docker_boot_guest_lab --phase wait --root {root}\n'
            f'ExecStart={binaries}/dockerd --host unix://{root}/engine.sock --config-file {root}/boot-daemon.json '
            f'--data-root {root}/data --exec-root {root}/boot-exec --pidfile {root}/boot-daemon.pid '
            '--storage-driver vfs --bridge none --iptables=false --ip6tables=false --ip-forward=false --ip-masq=false\n'
            '[Install]\nWantedBy=multi-user.target\n',
    }


def api(endpoint, method, route, body=None):
    connection = Client(endpoint)
    try:
        connection.request(method, route, body=body,
                           headers={} if body is None else {'Content-Type': 'application/json'})
        response = connection.getresponse()
        data = response.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise RuntimeError('Bounded fixture response required')
        return response.status, data
    finally:
        connection.close()


def wait_policy(root):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            status, body = api(root/'control/authorization.sock', 'POST', '/Plugin.Activate', b'{}')
            if status == 200 and json.loads(body) == {'Implements': ['authz']}:
                return
        except (OSError, ValueError):
            pass
        time.sleep(.2)
    raise RuntimeError('Deny policy not ready; engine must not start')


def prepare(root, source, binaries):
    require_guest()
    root, source, binaries = map(safe_path, (root, source, binaries))
    if (root/'.disposable_writer').read_bytes() != b'DISPOSABLE ONLY\n':
        raise RuntimeError('Previously marked synthetic writer required')
    if subprocess.run(['pgrep', '-x', 'dockerd'], capture_output=True, timeout=5).returncode != 1:
        raise RuntimeError('Existing daemon blocks boot preparation')
    with held_disposable_hold(root/'control') as verify:
        verify()
        if len(verify.quiesce_container_ids) != 1:
            raise RuntimeError('Exactly one previously selected fixture writer required')
        identity = next(iter(verify.quiesce_container_ids))
        manifest = {'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                    'identity': identity,
                    'hold_digest': hashlib.sha256((root/'control/maintenance.hold').read_bytes()).hexdigest(),
                    'media_digest': hashlib.sha256((root/'media/ticks').read_bytes()).hexdigest()}
    rendered = units(root, source, binaries)
    directory = Path('/etc/systemd/system')
    spec = Path('/etc/docker/plugins')/(PREFIX+'.spec')
    targets = [directory/name for name in rendered] + [spec, root/'boot-daemon.json', root/'boot-manifest.json']
    if any(os.path.lexists(path) for path in targets):
        raise RuntimeError('Existing boot fixture artifacts must not be overwritten')
    with spec.open('x') as output:
        output.write('unix://'+str(root/'control/authorization.sock'))
    with (root/'boot-daemon.json').open('x') as output:
        json.dump({'authorization-plugins': [PREFIX], 'live-restore': False}, output)
    with (root/'boot-manifest.json').open('x') as output:
        json.dump(manifest, output)
    for name, text in rendered.items():
        with (directory/name).open('x') as output:
            output.write(text)
    subprocess.run(['systemd-analyze', 'verify', *[str(directory/name) for name in rendered]], check=True)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'enable', PREFIX+'-engine.service'], check=True)
    # No start or reboot here: the caller explicitly reboots only the separate VM.
    return {'status': 'disposable_boot_units_prepared', 'fixture_only': True,
            'production_authorized': False, 'automatic_restoration': False}


def check(root):
    require_guest()
    root = safe_path(root)
    manifest = json.loads((root/'boot-manifest.json').read_text())
    if manifest['boot_id'] == Path('/proc/sys/kernel/random/boot_id').read_text().strip():
        raise RuntimeError('Real independent guest reboot required')
    for unit in (PREFIX+'-policy.service', PREFIX+'-engine.service'):
        subprocess.run(['systemctl', 'is-active', '--quiet', unit], check=True)
    for filename, expected in [('control/maintenance.hold', manifest['hold_digest']),
                               ('media/ticks', manifest['media_digest'])]:
        if hashlib.sha256((root/filename).read_bytes()).hexdigest() != expected:
            raise RuntimeError('Retained deny hold or fixture bytes changed')
    identity = manifest['identity']
    status, body = api(root/'engine.sock', 'GET', '/containers/'+identity+'/json')
    if status != 200:
        raise RuntimeError('Boot writer inspection unavailable')
    require_stopped_writer(json.loads(body), identity)
    if api(root/'engine.sock', 'POST', '/containers/'+identity+'/start')[0] != 403:
        raise RuntimeError('Boot start denial not established')
    time.sleep(2)
    if hashlib.sha256((root/'media/ticks').read_bytes()).hexdigest() != manifest['media_digest']:
        raise RuntimeError('Fixture writer resumed after boot')
    return {'status': 'disposable_guest_boot_hold_verified', 'boot_changed': True,
            'writer_stopped': True, 'start_denied': True, 'hold_and_media_unchanged': True,
            'fixture_only': True, 'production_authorized': False,
            'production_activation': 'disabled', 'writer_exclusion_verified': False,
            'restart_inhibition_verified': False, 'automatic_restoration': False}


def check_blocked(root):
    require_guest()
    root = safe_path(root)
    manifest = json.loads((root/'boot-manifest.json').read_text())
    previous = (root/'corrupt-test-boot-id').read_text().strip()
    if previous == Path('/proc/sys/kernel/random/boot_id').read_text().strip():
        raise RuntimeError('Real corrupt-hold guest reboot required')
    if hashlib.sha256((root/'control/maintenance.hold').read_bytes()).hexdigest() == manifest['hold_digest']:
        raise RuntimeError('Corrupt hold fixture not established')
    for unit in (PREFIX+'-policy.service', PREFIX+'-engine.service'):
        if subprocess.run(['systemctl', 'is-active', '--quiet', unit], timeout=5).returncode == 0:
            raise RuntimeError('Corrupt hold unexpectedly started a service')
    try:
        api(root/'engine.sock', 'GET', '/_ping')
    except OSError:
        pass
    else:
        raise RuntimeError('Unexpected reachable private engine')
    if hashlib.sha256((root/'media/ticks').read_bytes()).hexdigest() != manifest['media_digest']:
        raise RuntimeError('Synthetic bytes changed during corrupt-hold boot')
    return {'status': 'disposable_corrupt_hold_boot_blocked', 'fixture_only': True,
            'production_authorized': False, 'production_activation': 'disabled',
            'writer_exclusion_verified': False, 'restart_inhibition_verified': False,
            'automatic_restoration': False, 'fixture_bytes_unchanged': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('prepare', 'wait', 'check', 'check-blocked'), required=True)
    parser.add_argument('--root', required=True)
    parser.add_argument('--source')
    parser.add_argument('--docker-bin')
    args = parser.parse_args()
    if args.phase == 'prepare':
        result = prepare(args.root, args.source, args.docker_bin)
    elif args.phase == 'wait':
        require_guest()
        wait_policy(safe_path(args.root))
        result = {'status': 'disposable_policy_ready'}
    elif args.phase == 'check-blocked':
        result = check_blocked(args.root)
    else:
        result = check(args.root)
    print(json.dumps(result, sort_keys=True))
