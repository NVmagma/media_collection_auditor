import os
import shlex
from pathlib import Path
import subprocess

SCRIPT = Path(__file__).resolve().parents[1]/'scripts/sqlite_control_transport_probe.sh'


def execute(tmp_path, ss_body):
    for name, body in [('uname', 'echo Linux'), ('ss', ss_body)]:
        file = tmp_path/name
        file.write_text('#!/bin/sh\n'+body+'\n')
        file.chmod(0o700)
    # Isolate only the host/container marker from the test runner's namespace.
    probe = tmp_path/'probe.sh'
    probe.write_text(SCRIPT.read_text().replace('[ -f /.dockerenv ]',
        '[ -f '+shlex.quote(str(tmp_path/'container-marker'))+' ]'))
    return subprocess.run(['/bin/bash', str(probe)], capture_output=True, text=True,
                          env={**os.environ, 'PATH': str(tmp_path)+':/usr/bin:/bin'}, timeout=5)


def test_named_listeners_only_and_no_connection_calls(tmp_path):
    result = execute(tmp_path, '''
case "$*" in
'-H -lntp')
 echo 'LISTEN 0 4096 127.0.0.1:2375 0.0.0.0:* users:(("dockerd",pid=10,fd=3))'
 echo 'LISTEN 0 128 127.0.0.1:9999 0.0.0.0:* users:(("unrelated",pid=20,fd=4))';;
'-H -lxnp')
 echo 'u_str LISTEN 0 4096 /run/containerd/containerd.sock 12 * 0 users:(("containerd",pid=11,fd=5))';;
*) exit 99;;
esac''')
    assert result.returncode == 0
    assert 'tcp_listener=LISTEN' in result.stdout
    assert '/run/containerd/containerd.sock' in result.stdout
    assert 'unrelated' not in result.stdout and '9999' not in result.stdout
    assert 'status=listener_snapshot_complete' in result.stdout
    assert 'production_authorized=false' in result.stdout


def test_absence_is_never_claimed_as_exclusion(tmp_path):
    result = execute(tmp_path, 'exit 0')
    assert result.returncode == 0
    assert 'tcp_status=no_named_listener_observed' in result.stdout
    assert 'unix_status=no_named_listener_observed' in result.stdout
    assert 'writer_exclusion_verified=false' in result.stdout
    assert 'missing process visibility is unknown coverage' in result.stdout


def test_query_failure_remains_incomplete_without_raw_diagnostics(tmp_path):
    result = execute(tmp_path, 'echo private-error >&2; exit 1')
    assert result.returncode == 2
    assert 'status=listener_observation_incomplete' in result.stdout
    assert 'private-error' not in result.stdout + result.stderr


def test_container_context_rejected_before_listener_queries(tmp_path):
    (tmp_path/'container-marker').touch()
    result = execute(tmp_path, 'echo unexpected-listener-call; exit 0')
    assert result.returncode == 2
    assert 'status=wrong_execution_context' in result.stdout
    assert 'unexpected-listener-call' not in result.stdout
