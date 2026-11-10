"""Read private regular files within size limits and check that they did not change."""
import json,os,stat
LIMIT=64*1024*1024

def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_nlink)

def _read(fd):
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= LIMIT:
        raise RuntimeError('Bounded regular single-link release input required')
    chunks, offset = [], 0
    while offset <= LIMIT:
        chunk = os.pread(fd, min(1024 * 1024, LIMIT + 1 - offset), offset)
        if not chunk:
            break
        chunks.append(chunk); offset += len(chunk)
    payload = b''.join(chunks)
    if len(payload) != info.st_size or _identity(os.fstat(fd)) != _identity(info):
        raise RuntimeError('Release input changed during read')
    return payload, info

def _encode(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('ascii') + b'\n'

def _local(parent, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        raw, info = _read(fd)
        if _identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != _identity(info):
            raise RuntimeError('Recovery artifact changed during read')
        return raw, info
    finally:
        os.close(fd)
