"""No real mounts, NFS controls, SSH or Docker in these local regressions."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess

import pytest

SCRIPTS = Path(__file__).parents[1] / 'scripts'
spec = importlib.util.spec_from_file_location('mac_client', SCRIPTS/'sqlite_nfs_mac_client.py')
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)
NONCE = 'a'*32


def args(**kwargs):
    return argparse.Namespace(**dict(address='172.17.0.31', lab='/mnt/media/sql_test/nfs-mac.Fixture',
                                    nonce=NONCE, phase_script='/mnt/user/checkout/scripts/sqlite_nfs_mac_phase.sh', **kwargs))


@pytest.mark.parametrize('field,value', [('address','127.0.0.1'), ('address','8.8.8.8'),
    ('address','::1'), ('nonce','bad'), ('lab','/mnt/user/media_storage'),
    ('lab','/mnt/../nfs-mac.Fixture'), ('phase_script','/etc/rc.d/rc.nfsd')])
def test_client_rejects_nonfixture_identity_before_actions(field, value):
    options = args()
    setattr(options, field, value)
    with pytest.raises(ValueError):
        client.validate(options)


def test_remote_phase_command_is_fixed_and_rejects_arbitrary_actions():
    options = args()
    client.validate(options)
    command = client.remote_command(options, 'pause')
    assert command.split() == ['bash', options.phase_script, options.lab, NONCE, 'pause']
    with pytest.raises(ValueError):
        client.remote_command(options, 'restart')


def fixture(tmp_path):
    root = tmp_path/'nfs-mac.Fixture'
    (root/'data').mkdir(parents=True)
    (root/'control').mkdir()
    (root/'data'/'.fixture-only').write_text('DISPOSABLE MAC NFS FIXTURE '+NONCE+'\n')
    return root


@pytest.mark.parametrize('phase,previous', [('pause','ready'), ('observe','pause.ready'),
    ('restore','observe.ready'), ('verify','restore.ready'), ('finish','verify.ready')])
def test_phase_requires_order_nonce_and_single_request(tmp_path, phase, previous):
    root = fixture(tmp_path)
    command = ['bash', str(SCRIPTS/'sqlite_nfs_mac_phase.sh'), str(root), NONCE, phase]
    def call():
        return subprocess.run(command, text=True, capture_output=True, timeout=5)
    assert call().returncode != 0
    assert not (root/'control'/f'{phase}.request').exists()
    (root/'control'/previous).touch()
    (root/'control'/f'{phase}.ready').touch()
    assert call().stdout.strip() == 'fixture_phase='+phase
    assert (root/'control'/f'{phase}.request').read_text() == NONCE+'\n'
    assert call().returncode != 0


def test_wrong_nonce_never_writes_phase_request(tmp_path):
    root = fixture(tmp_path)
    (root/'control'/'ready').touch()
    result = subprocess.run(['bash', str(SCRIPTS/'sqlite_nfs_mac_phase.sh'), str(root), 'b'*32, 'pause'], timeout=5)
    assert result.returncode != 0
    assert not (root/'control'/'pause.request').exists()


def test_writer_reports_write_and_fsync_separately_on_disposable_regular_file(tmp_path):
    target = tmp_path/'payload'
    target.write_bytes(client.BEFORE)
    fd = os.open(target, os.O_RDWR)
    reader, writer = os.pipe()
    child = os.fork()
    if child == 0:
        os.close(reader)
        client.writer(fd, writer)
    os.close(writer)
    try:
        messages = client.collect_messages(reader, 5, [])
        assert messages == ['write_returned', 'fsync_returned']
        _, status = os.waitpid(child, 0)
        assert status == 0
        assert target.read_bytes() == client.PENDING
    finally:
        os.close(reader)
        os.close(fd)


@pytest.mark.parametrize('net,mnt', [('host-net','private-mnt'), ('private-net','host-mnt'), ('wrong-net','private-mnt')])
def test_server_rejects_reused_namespaces_before_privileged_setup(tmp_path, net, mnt):
    tools = tmp_path/'bin'
    tools.mkdir()
    for name, body in {
        'readlink': 'case "$1" in */net) echo "$TEST_NET";; *) echo "$TEST_MNT";; esac',
        'mount': 'touch "$MUTATED"; exit 77',
    }.items():
        tool=tools/name
        tool.write_text('#!/bin/sh\n'+body+'\n')
        tool.chmod(0o755)
    result=subprocess.run(['bash', str(SCRIPTS/'sqlite_nfs_mac_server.sh'), str(tmp_path),
                           'host-net','host-mnt','host-control','private-net'],
                          env={**os.environ, 'PATH':str(tools)+os.pathsep+os.defpath,
                               'TEST_NET':net,'TEST_MNT':mnt,'MUTATED':str(tmp_path/'mutated')},
                          capture_output=True,timeout=5)
    assert result.returncode != 0
    assert not (tmp_path/'mutated').exists()


def test_launcher_has_no_published_ports_or_module_service_commands():
    launcher=(SCRIPTS/'sqlite_nfs_mac_lab.sh').read_text()
    server=(SCRIPTS/'sqlite_nfs_mac_server.sh').read_text()
    assert '--network bridge' in launcher
    assert '--net="/proc/self/fd/$net_fd"' in launcher
    create = launcher.split('docker create', 1)[1].split('\nours', 1)[0]
    assert '--publish' not in create and ' -p ' not in create
    assert '--kill-child' in launcher
    assert 'before=$(snapshot)' in launcher and '"$(snapshot)" = "$before"' in launcher
    for command in ('modprobe ', 'insmod ', 'sysctl ', 'rc.nfsd stop', 'rc.nfsd start'):
        assert command not in launcher+server
    assert '"$gateway" > "$lab/etc/exports"' in launcher
    assert 'all_squash' in launcher


def test_buffered_write_return_does_not_imply_fsync_completion(tmp_path, monkeypatch):
    target = tmp_path/'payload'
    target.write_bytes(client.BEFORE)
    fd = os.open(target, os.O_RDWR)
    reader, reporter = os.pipe()
    release, controller = os.pipe()
    real_fsync = os.fsync
    def delayed_fsync(descriptor):
        assert os.read(release, 1) == b'x'
        real_fsync(descriptor)
    monkeypatch.setattr(client.os, 'fsync', delayed_fsync)
    child = os.fork()
    if child == 0:
        os.close(reader)
        os.close(controller)
        client.writer(fd, reporter)
    os.close(reporter)
    os.close(release)
    try:
        messages = client.collect_messages(reader, 1, [])
        assert messages == ['write_returned']
        os.write(controller, b'x')
        client.collect_messages(reader, 5, messages)
        assert messages == ['write_returned', 'fsync_returned']
        assert os.waitpid(child, 0)[1] == 0
    finally:
        os.close(controller)
        os.close(reader)
        os.close(fd)


@pytest.mark.parametrize('responds', [True, False])
def test_private_rpc_readiness_uses_direct_null_not_registration_dump(tmp_path, responds):
    server = (SCRIPTS/'sqlite_nfs_mac_server.sh').read_text()
    function = 'wait_rpc(){\n'+server.split('wait_rpc(){\n', 1)[1].split('\n}\n', 1)[0]+'\n}\n'
    tools = tmp_path/'bin'
    tools.mkdir()
    calls = tmp_path/'calls'
    for name, body in {
        'timeout': 'shift; shift; exec "$@"',
        'sleep': ':',
        'rpcinfo': '''printf '%s\\n' "$*" >> "$RPC_CALLS"
case "$1" in -p) echo 'RPC: Authentication error; why = Client credential too weak' >&2; exit 1;; esac
[ "$1" = -a ] && [ "$3" = -T ] && [ "$4" = tcp ] || exit 99
[ "$RPC_RESPONDS" = yes ] || { echo 'RPC: endpoint unavailable' >&2; exit 1; }
echo 'program ready and waiting' ''',
    }.items():
        tool=tools/name
        tool.write_text('#!/bin/sh\n'+body+'\n')
        tool.chmod(0o755)
    code='lab=$1\n'+function+'wait_rpc rpcbind 127.0.0.1.0.111 100000 2\n'
    result=subprocess.run(['bash','-eu','-s','--',str(tmp_path)], input=code,
        capture_output=True,text=True,timeout=5,
        env={**os.environ,'PATH':str(tools)+os.pathsep+os.defpath,
             'RPC_CALLS':str(calls),'RPC_RESPONDS':'yes' if responds else 'no'})
    queries=calls.read_text().splitlines()
    assert queries == ['-a 127.0.0.1.0.111 -T tcp 100000 2'] * (1 if responds else 20)
    assert (result.returncode == 0) == responds
    if responds:
        assert 'private_rpc_ready=rpcbind' in result.stdout
    else:
        assert 'private_rpc_unavailable=rpcbind' in result.stderr
        assert 'private_rpc_ready=' not in result.stdout
    assert '-i' not in server.split('rpcbind -f',1)[1].split('\n',1)[0]
    assert 'wait_rpc mountd 127.0.0.1.78.80 100005 3' in server


def test_launcher_reports_early_child_exit_with_retained_log(tmp_path):
    (tmp_path/'control').mkdir()
    (tmp_path/'server.log').write_text('fixture setup rejected\n')
    launcher=(SCRIPTS/'sqlite_nfs_mac_lab.sh').read_text()
    body=launcher.split('for attempt in $(seq 1 600); do',1)[1].split("printf 'fixture_ready",1)[0]
    code='lab=$1\n(exit 17) &\nserver=$!\nwait "$server" || :\nfor attempt in $(seq 1 600); do'+body
    result=subprocess.run(['bash','-eu','-s','--',str(tmp_path)],input=code,
                          text=True,capture_output=True,timeout=5)
    assert result.returncode == 2
    assert 'private_server_exit_code=17' in result.stdout
    assert 'fixture setup rejected' in result.stdout
    assert 'No such process' not in result.stderr
    assert 'fixture_ready=true' not in result.stdout
