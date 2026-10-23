#!/usr/bin/env python3
"""Mac-only fixed synthetic write/recovery driver; never targets existing mounts."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import select
import shlex
import socket
import stat
import subprocess
import sys
import tempfile
import time

BEFORE = b"BEFORE!\n"
PENDING = b"PENDING\n"


def validate(args):
    address = ipaddress.ip_address(args.address)
    if address.version != 4 or not address.is_private or address.is_loopback:
        raise ValueError("Private fixture IPv4 required")
    for path in (args.lab, args.phase_script):
        if not re.fullmatch(r"/[A-Za-z0-9_./-]+", path) or ".." in path.split('/'):
            raise ValueError("Absolute fixture paths required")
    if not re.fullmatch(r"[0-9a-f]{32}", args.nonce) or not re.search(r"/nfs-mac\.[A-Za-z0-9]+$", args.lab):
        raise ValueError("New fixture identity required")
    if not args.phase_script.endswith('/scripts/sqlite_nfs_mac_phase.sh'):
        raise ValueError("Fixed fixture phase helper required")


def free_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def remote_command(args, phase):
    if phase not in ('pause', 'observe', 'restore', 'verify', 'finish'):
        raise ValueError('Unknown fixture phase')
    return shlex.join(['bash', args.phase_script, args.lab, args.nonce, phase])


def collect_messages(fd, seconds, messages):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], min(0.2, max(0, deadline-time.monotonic())))
        if ready:
            data = os.read(fd, 4096)
            if not data:
                break
            messages.extend(data.decode('ascii').splitlines())
    return messages


def writer(fd, pipe):
    try:
        written = os.pwrite(fd, PENDING, 0)
        if written != len(PENDING):
            raise RuntimeError('Short fixture write')
        os.write(pipe, b'write_returned\n')
        os.fsync(fd)
        os.write(pipe, b'fsync_returned\n')
        os._exit(0)
    except BaseException:
        os.write(pipe, b'writer_failed\n')
        os._exit(1)


def run(args):
    validate(args)
    if sys.platform != 'darwin':
        raise RuntimeError('Run on the real Mac client, not Tower or a container')
    # All client state and the mountpoint are new; no existing share is remounted.
    scratch = Path(tempfile.mkdtemp(prefix='auditor-nfs-mac-'))
    mountpoint = scratch / 'mount'
    mountpoint.mkdir()
    control = str(scratch / 'ssh-control')
    ports = [free_port(), free_port()]
    while ports[0] == ports[1]:
        ports[1] = free_port()
    command = ['ssh', '-M', '-S', control, '-N', '-T',
               '-o', 'ControlPersist=no', '-o', 'ExitOnForwardFailure=yes',
               '-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=15',
               '-L', f'127.0.0.1:{ports[0]}:{args.address}:2049',
               '-L', f'127.0.0.1:{ports[1]}:{args.address}:20048', 'root@10.0.0.10']
    print('client_fixture_directory='+str(scratch), flush=True)
    tunnel = subprocess.Popen(command)
    mounted = False
    fd = None
    child = None
    read_pipe = None
    try:
        for _ in range(300):
            if tunnel.poll() is not None:
                raise RuntimeError('Fixture SSH tunnel failed')
            if Path(control).exists():
                break
            time.sleep(0.1)
        if not Path(control).exists():
            raise RuntimeError('SSH setup timed out')

        def phase(name):
            result = subprocess.run(['ssh', '-S', control, '-o', 'BatchMode=yes',
                                     'root@10.0.0.10', remote_command(args, name)],
                                    capture_output=True, text=True, timeout=55)
            if result.returncode or result.stdout.strip() != 'fixture_phase='+name:
                raise RuntimeError('Fixture phase uncertain: '+name)

        options = f'vers=3,tcp,port={ports[0]},mountport={ports[1]},resvport,nomntudp,nolocks,hard,nointr'
        # A process timeout cannot prove kernel mount cancellation; retain scratch on failure.
        mounted = True  # also retain on an uncertain mount outcome
        subprocess.run(['sudo', '/sbin/mount', '-t', 'nfs', '-o', options,
                        '127.0.0.1:'+args.lab+'/data', str(mountpoint)], check=True, timeout=60)
        marker = (mountpoint / '.fixture-only').read_bytes()
        if marker != ('DISPOSABLE MAC NFS FIXTURE '+args.nonce+'\n').encode():
            raise RuntimeError('Fixture identity mismatch; no write performed')
        fd = os.open(mountpoint / 'payload.bin', os.O_RDWR | os.O_NOFOLLOW)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != 8:
            raise RuntimeError('Unexpected fixture payload identity')
        if os.pread(fd, 9, 0) != b'INITIAL\n':
            raise RuntimeError('Unexpected initial fixture bytes')
        if os.pwrite(fd, BEFORE, 0) != len(BEFORE):
            raise RuntimeError('Short baseline write')
        os.fsync(fd)
        phase('pause')  # server kills its pause worker before acknowledging
        read_pipe, write_pipe = os.pipe()
        child = os.fork()
        if child == 0:
            os.close(read_pipe)
            writer(fd, write_pipe)
        os.close(write_pipe)
        messages = collect_messages(read_pipe, 5, [])
        if 'fsync_returned' in messages or 'writer_failed' in messages:
            raise RuntimeError('Unexpected paused write outcome')
        phase('observe')  # independent server bytes must remain BEFORE
        print(json.dumps({'status':'paused_fixture_observed', 'fixture_only':True,
                          'write_returned':'write_returned' in messages,
                          'fsync_completed':False, 'write_outcome':'uncertain',
                          'production_authorized':False}), flush=True)
        phase('restore')  # explicit fixture recovery step; never an error-cleanup action
        collect_messages(read_pipe, 35, messages)
        if 'fsync_returned' not in messages or 'writer_failed' in messages:
            raise RuntimeError('Fixture write remains uncertain after recovery')
        _, status = os.waitpid(child, 0)
        child = None
        if status:
            raise RuntimeError('Fixture writer failed')
        phase('verify')  # server must independently observe PENDING
        os.close(fd)
        fd = None
        subprocess.run(['sudo', '/sbin/umount', str(mountpoint)], check=True, timeout=30)
        mounted = False
        phase('finish')  # teardown allowed only after successful client unmount
        print(json.dumps({'status':'real_mac_nfs3_recovery_fixture_complete',
                          'fixture_only':True, 'client_unmounted':True,
                          'paused_write_outcome':'uncertain', 'recovered_fsync_completed':True,
                          'production_authorized':False, 'production_activation':'disabled',
                          'writer_exclusion_verified':False, 'restart_inhibition_verified':False}))
    finally:
        if fd is not None:
            os.close(fd)
        if read_pipe is not None:
            os.close(read_pipe)
        if mounted or child is not None:
            # Never claim that killing a user process drains kernel writeback.
            print(f'Fixture outcome uncertain. Retained client state: {scratch}', file=sys.stderr)
            print(f'Owned SSH tunnel PID: {tunnel.pid}; writer PID: {child}', file=sys.stderr)
            print('Do not reuse this mount or infer that pending writes are gone. No automatic restoration performed.', file=sys.stderr)
        else:
            tunnel.terminate()
            try:
                tunnel.wait(timeout=10)
            except subprocess.TimeoutExpired:
                tunnel.kill()
                tunnel.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ('address', 'lab', 'nonce', 'phase-script'):
        parser.add_argument('--'+field, required=True)
    args = parser.parse_args()
    try:
        run(args)
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError):
        print('status=blocked; fixture recovery/teardown may require review; no production action authorized', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
