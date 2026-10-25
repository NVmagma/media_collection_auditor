"""Read one stable current state/config file to private redirected stdout only.

Run through the existing container's Python/stdin; stdlib only, no app imports,
locks, network or writes. Metadata goes to separately redirected stderr. Neither
stream is suitable for pasting: the data stream may contain credentials/titles.
"""
import hashlib
import json
import os
from pathlib import PurePosixPath
import stat
import sys


def capture(kind):
    key, default = {'config': ('WEB_CONFIG_FILE', '/app/logs/auditor_config.json'),
                    'state': ('STATE_FILE', '/app/logs/auditor_state.json')}[kind]
    path = os.environ.get(key, default)
    parsed = PurePosixPath(path)
    if (not path.startswith('/app/logs/') or str(parsed) != path or '..' in parsed.parts
            or any(ord(c) < 32 or ord(c) == 127 for c in path)):
        raise RuntimeError('Unsupported capture path')
    parent = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    fd = None
    try:
        for part in parsed.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent); parent = child
        fd = os.open(parsed.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= 64 * 1024 * 1024:
            raise RuntimeError('Unsafe capture input')
        raw, offset = [], 0
        while offset <= 64 * 1024 * 1024:
            chunk = os.pread(fd, min(1024 * 1024, 64 * 1024 * 1024 + 1 - offset), offset)
            if not chunk: break
            raw.append(chunk); offset += len(chunk)
        raw = b''.join(raw)
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_nlink)
        if (len(raw) != before.st_size or identity(os.fstat(fd)) != identity(before)
                or identity(os.stat(parsed.name, dir_fd=parent, follow_symlinks=False)) != identity(before)):
            raise RuntimeError('Capture input changed')
        report = {'kind': kind, 'path': path, 'sha256': hashlib.sha256(raw).hexdigest(),
            'bytes': len(raw), 'uid': before.st_uid, 'gid': before.st_gid,
            'process_uid': os.geteuid(), 'quiescent': False}
        sys.stdout.buffer.write(raw)
        print(json.dumps(report, sort_keys=True), file=sys.stderr)
    finally:
        if fd is not None: os.close(fd)
        os.close(parent)


if __name__ == '__main__':
    try:
        capture(sys.argv[1])
    except Exception:
        print('{"status":"private_capture_failed"}', file=sys.stderr)
        raise SystemExit(1)
