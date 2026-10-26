"""Deny-only durable state for the disposable Docker authorization fixture.

No production caller, release/expiry API, ownership permit or service controls.
"""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import stat
from app.sqlite_docker_quiesce_policy import validate_scope

MARKER = b'DISPOSABLE ONLY\n'
HOLD = b'{"schema_version":1,"phase":"fence_requested","automatic_restoration":false}\n'


def _root(root):
    root = Path(root)
    if not root.is_absolute() or root.resolve() != root or not stat.S_ISDIR(root.lstat().st_mode):
        raise RuntimeError('Canonical marked authorization fixture required')
    return root


def _identity(info):
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise RuntimeError('Unsafe authorization fixture state')
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read_at(directory, name, expected):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        identity = _identity(os.fstat(fd))
        if os.read(fd, len(expected)+1) != expected or _identity(os.fstat(fd)) != identity:
            raise RuntimeError('Authorization hold invalid or changed')
        current = os.stat(name, dir_fd=directory, follow_symlinks=False)
        if _identity(current) != identity:
            raise RuntimeError('Authorization hold entry changed')
        return identity
    finally:
        os.close(fd)


def create_disposable_hold(root, *, container_ids=()):
    """Create new fixed deny state exclusively; failure leaves partial evidence."""
    scope = sorted(validate_scope(container_ids))
    root = _root(root)
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        _read_at(directory, '.disposable_authorization', MARKER)
        for name, content in (('authorization.lock', b''), ('maintenance.hold', HOLD),
                              ('quiesce.json', (json.dumps(scope,separators=(',',':'))+'\n').encode())):
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
            try:
                view = memoryview(content)
                while view:
                    written = os.write(fd, view)
                    if not written:
                        raise RuntimeError('Authorization hold write incomplete')
                    view = view[written:]
                os.fsync(fd)
            finally:
                os.close(fd)
        os.fsync(directory)
        parent = os.open(root.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        os.close(directory)


@contextmanager
def held_disposable_hold(root):
    """Reopen persisted deny-only evidence; never authorize writer ownership."""
    root = _root(root)
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    lock = None
    try:
        held = os.fstat(directory)
        marker = _read_at(directory, '.disposable_authorization', MARKER)
        hold = _read_at(directory, 'maintenance.hold', HOLD)
        scope_fd = os.open('quiesce.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            _identity(os.fstat(scope_fd))
            scope_content = os.read(scope_fd, 8193)
        finally:
            os.close(scope_fd)
        if len(scope_content)>8192:
            raise RuntimeError('Authorization scope exceeds bound')
        scope = validate_scope(json.loads(scope_content))
        expected_scope = (json.dumps(sorted(scope),separators=(',',':'))+'\n').encode()
        if scope_content != expected_scope:
            raise RuntimeError('Noncanonical authorization scope')
        scope_identity = _read_at(directory, 'quiesce.json', expected_scope)
        lock = os.open('authorization.lock', os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
                       dir_fd=directory)
        lock_identity = _identity(os.fstat(lock))
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another authorization fixture is active') from None
        def verify():
            current = root.lstat()
            if (not stat.S_ISDIR(current.st_mode)
                    or (current.st_dev,current.st_ino) != (held.st_dev,held.st_ino)
                    or _read_at(directory, '.disposable_authorization', MARKER) != marker
                    or _read_at(directory, 'maintenance.hold', HOLD) != hold
                    or _read_at(directory, 'quiesce.json', expected_scope) != scope_identity
                    or _identity(os.stat('authorization.lock', dir_fd=directory,
                                         follow_symlinks=False)) != lock_identity
                    or _identity(os.fstat(lock)) != lock_identity):
                raise RuntimeError('Authorization fixture binding changed')
        verify.quiesce_container_ids = scope
        verify()
        yield verify
        verify()
    finally:
        if lock is not None:
            os.close(lock)
        os.close(directory)
