"""Held path/mount observations for disposable media; never writer exclusion.

The caller still owns the runner lock and the actual external writer fences.
Different mounts and filesystem types are allowed. No directory contents are
frozen by this observer, and no metadata sample confers production authority.
"""
from contextlib import contextmanager, ExitStack
import os
from pathlib import Path
import stat

from app.sqlite_rename_mount_binding import (
    read_fd_mount_id, read_mount_namespace_identity,
)


@contextmanager
def held_disposable_storage_observer(*, root):
    root = Path(root)
    if not root.is_absolute() or root.resolve() != root:
        raise ValueError('Canonical disposable storage root required')
    failed = False
    active = True
    names = ('.', 'transient', 'holding', 'keep', 'removal')
    with ExitStack() as stack:
        def open_directory(path):
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            stack.callback(os.close, fd)
            return fd
        root_fd = open_directory(root)
        marker_fd = os.open('.sqlite_disposable_rehearsal',
                            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                            dir_fd=root_fd)
        stack.callback(os.close, marker_fd)
        marker = os.fstat(marker_fd)
        if (not stat.S_ISREG(marker.st_mode) or marker.st_nlink != 1
                or os.pread(marker_fd, 64, 0) != b'DISPOSABLE ONLY\n'):
            raise RuntimeError('Disposable storage marker required')
        held = {name: open_directory(root / name) for name in names}
        def identity(fd):
            info = os.fstat(fd)
            return info.st_dev, info.st_ino, read_fd_mount_id(fd)
        expected = {name: identity(fd) for name, fd in held.items()}
        if identity(root_fd) != expected['.']:
            raise RuntimeError('Disposable storage root changed during capture')
        namespace = read_mount_namespace_identity()
        def sample():
            if root.resolve() != root or read_mount_namespace_identity() != namespace:
                raise RuntimeError('Disposable storage namespace/path changed')
            current_marker = os.stat('.sqlite_disposable_rehearsal', dir_fd=root_fd,
                                     follow_symlinks=False)
            if (not stat.S_ISREG(current_marker.st_mode)
                    or current_marker.st_nlink != 1
                    or (current_marker.st_dev, current_marker.st_ino) !=
                       (marker.st_dev, marker.st_ino)
                    or os.pread(marker_fd, 64, 0) != b'DISPOSABLE ONLY\n'):
                raise RuntimeError('Disposable storage marker changed')
            for name, fd in held.items():
                fresh = os.open(root / name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    if identity(fd) != expected[name] or identity(fresh) != expected[name]:
                        raise RuntimeError('Disposable storage mount/path changed')
                finally:
                    os.close(fresh)
        def verify():
            nonlocal failed
            if failed or not active:
                raise RuntimeError('Disposable storage observer closed or failed; review required')
            try:
                sample()
                sample()
            except BaseException:
                failed = True
                raise
        try:
            verify()
            yield verify
        finally:
            active = False
