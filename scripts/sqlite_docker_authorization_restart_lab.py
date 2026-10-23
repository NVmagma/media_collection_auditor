"""Local disposable nested-daemon rehearsal; never configures the outer daemon.

Explicit local Unix outer socket and cached immutable image IDs required. No
privileged mode, published ports, host socket mounts or image pulls/builds.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time
import uuid


def run_lab(*, host, daemon_image, python_image):
    if not re.fullmatch(r'unix:///[^\n\r]+', host):
        raise ValueError('Explicit local Unix socket required')
    for image in (daemon_image, python_image):
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', image):
            raise ValueError('Cached immutable image IDs required')
    repo = Path(__file__).resolve().parents[1]
    docker = ['docker', '--host', host]
    def call(*args, timeout=45):
        result = subprocess.run([*docker, *args], capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            raise RuntimeError('Disposable Docker command failed: ' + args[0] + ': ' + result.stderr[-1200:])
        return result.stdout.strip()
    if call('info', '--format', '{{.OperatingSystem}}') != 'Docker Desktop':
        raise RuntimeError('Local Docker Desktop rehearsal required; do not run on Tower')
    for image in (daemon_image, python_image):
        call('image', 'inspect', image, '--format', '{{.Id}}')
    nonce = 'mca-authz-' + uuid.uuid4().hex[:12]
    volume, policy, daemon = nonce+'-volume', nonce+'-policy', nonce+'-daemon'
    containers = []
    volume_created = False
    label = 'org.nvmagma.auditor.fixture=' + nonce
    results = {}
    active_policy = policy
    try:
        call('volume', 'create', '--label', label, volume)
        volume_created = True
        shared = ['--mount', f'type=volume,src={volume},dst=/fixture']
        sources = ['--mount', f'type=bind,src={repo}/app,dst=/src/app,readonly',
                   '--mount', f'type=bind,src={repo}/scripts,dst=/src/scripts,readonly',
                   '-e', 'PYTHONPATH=/src']
        common = ['--pull', 'never', '--network', 'none', '--cap-drop', 'ALL',
                  '--security-opt', 'no-new-privileges', '--pids-limit', '128', '--cpus', '1']
        call('run', '-d', '--name', policy, '--label', label, *common,
             '--read-only', '--memory', '128m', '--user', '0', *shared, *sources,
             '--entrypoint', 'python', python_image, '-B', '-m',
             'scripts.sqlite_docker_authorization_fixture', '--root', '/fixture/control')
        containers.append(policy)
        deadline = time.monotonic()+20
        while True:
            ready = call('exec', active_policy, 'python', '-c',
                         "from pathlib import Path; print(Path('/fixture/control/authorization.sock').is_socket())")
            if ready == 'True': break
            if time.monotonic() > deadline: raise RuntimeError('Private plugin startup timeout')
            time.sleep(.2)
        call('run', '-d', '--name', daemon, '--label', label, *common,
             '--cap-add', 'CHOWN', '--cap-add', 'DAC_OVERRIDE', '--memory', '384m', *shared,
             '--mount', f'type=volume,src={volume},dst=/etc/docker/plugins,volume-subpath=control,readonly',
             '--entrypoint', 'dockerd', daemon_image, '--host', 'unix:///fixture/engine.sock',
             '--authorization-plugin=plugin', '--data-root', '/tmp/fixture-data',
             '--exec-root', '/tmp/fixture-exec', '--pidfile', '/tmp/fixture.pid',
             '--storage-driver', 'vfs', '--bridge', 'none', '--iptables=false',
             '--ip6tables=false', '--ip-forward=false', '--ip-masq=false')
        containers.append(daemon)
        def await_ready():
            deadline = time.monotonic()+20
            while True:
                try:
                    state = call('exec', active_policy, 'python', '-c',
                    "import socket; s=socket.socket(socket.AF_UNIX); s.settimeout(1); "
                    "s.connect('/fixture/engine.sock'); s.sendall(b'GET /_ping HTTP/1.0\\r\\n\\r\\n'); "
                    "print(s.recv(128).splitlines()[0].decode()); s.close()")
                except RuntimeError:
                    state = ''
                if '200' in state: return
                if time.monotonic() > deadline: raise RuntimeError('Private daemon startup timeout')
                time.sleep(.2)
        def probe(unavailable=False, hold_invalid=False):
            args = ['-B', '-m', 'scripts.sqlite_docker_authorization_client', '--root', '/fixture']
            if hold_invalid:
                args.append('--hold-invalid')
            if unavailable:
                args.append('--plugin-unavailable')
                output = call('run', '--rm', '--label', label, *common, '--read-only',
                    '--memory', '128m', '--user', '0', *shared, *sources,
                    '--entrypoint', 'python', python_image, *args)
            else:
                output = call('exec', active_policy, 'python', *args)
            return json.loads(output)
        await_ready()
        results['initial'] = probe()
        call('restart', daemon)
        await_ready()
        results['after_daemon_restart'] = probe()
        hold_digest = call('exec', active_policy, 'python', '-c',
            "import hashlib; from pathlib import Path; print(hashlib.sha256(Path('/fixture/control/maintenance.hold').read_bytes()).hexdigest())")
        call('kill', active_policy)
        results['after_plugin_death'] = probe(True)
        call('exec', daemon, 'sh', '-c',
             'test -z "$(ls -A /tmp/fixture-data/containers)"')
        results['private_container_inventory_empty'] = True
        active_policy = nonce+'-reload'
        call('run', '-d', '--name', active_policy, '--label', label, *common,
             '--read-only', '--memory', '128m', '--user', '0', *shared, *sources,
             '--entrypoint', 'python', python_image, '-B', '-m',
             'scripts.sqlite_docker_authorization_fixture', '--root', '/fixture/control',
             '--resume-fixture')
        containers.append(active_policy)
        await_ready()
        results['after_persisted_hold_reload'] = probe()
        after_digest = call('exec', active_policy, 'python', '-c',
            "import hashlib; from pathlib import Path; print(hashlib.sha256(Path('/fixture/control/maintenance.hold').read_bytes()).hexdigest())")
        if hold_digest != after_digest:
            raise RuntimeError('Persisted hold bytes changed during reload')
        results['hold_bytes_unchanged_after_reload'] = True
        call('exec', active_policy, 'python', '-c',
             "from pathlib import Path; Path('/fixture/control/maintenance.hold').write_bytes(b'corrupt fixture hold')")
        results['after_hold_corruption'] = probe(hold_invalid=True)
        call('restart', daemon)
        deadline = time.monotonic()+40
        while call('inspect', '--format', '{{.State.Running}}', daemon) == 'true':
            if time.monotonic() > deadline:
                raise RuntimeError('Private daemon did not fail startup without plugin')
            time.sleep(.5)
        exit_code = call('inspect', '--format', '{{.State.ExitCode}}', daemon)
        if exit_code == '0': raise RuntimeError('Private daemon exited without failure evidence')
        diagnostic = subprocess.run([*docker, 'logs', '--tail', '30', daemon],
            capture_output=True, text=True, timeout=10)
        if diagnostic.returncode or 'failed to validate authorization plugin' not in (diagnostic.stdout + diagnostic.stderr):
            raise RuntimeError('Plugin-specific startup failure not established')
        results['restart_with_invalid_hold'] = 'plugin_validation_failed'
        return {'status': 'private_daemon_restart_rehearsal_complete', 'results': results,
                'fixture_only': True, 'automatic_restoration': False,
                'production_authorized': False, 'restart_inhibition_verified': False}
    finally:
        # Only names uniquely created here; no global prune or existing-service controls.
        for name in reversed(containers):
            call('rm', '-f', '-v', name)
        if volume_created:
            call('volume', 'rm', volume)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--outer-host', required=True)
    parser.add_argument('--daemon-image', required=True)
    parser.add_argument('--python-image', required=True)
    args = parser.parse_args()
    print(json.dumps(run_lab(host=args.outer_host, daemon_image=args.daemon_image,
                             python_image=args.python_image), sort_keys=True))
