"""Move a folder on Linux without overwriting an existing destination.

Do not fall back to os.rename. Another process could create the destination
after the initial check. If the filesystem cannot do this safely, stop and leave
the pending intent in place.
"""

from __future__ import annotations

import ctypes
import errno
import os
from pathlib import Path
import sys
import stat

_AT_FDCWD = -100
_RENAME_NOREPLACE = 1


def rename_directory_noreplace(source: str | Path, destination: str | Path) -> None:
    """Rename in one step without overwriting a destination that appeared after our check."""
    if sys.platform != "linux":
        raise RuntimeError("Atomic no-replace rename requires Linux")
    source, destination = os.fspath(source), os.fspath(destination)
    _renameat2(_AT_FDCWD, source, _AT_FDCWD, destination)


def _renameat2(source_fd, source, destination_fd, destination):
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise RuntimeError("renameat2 unavailable; refusing unsafe fallback")
    renameat2.argtypes = [
        ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
        ctypes.c_char_p, ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    rc = renameat2(source_fd, os.fsencode(source),
                   destination_fd, os.fsencode(destination), _RENAME_NOREPLACE)
    if rc != 0:
        error = ctypes.get_errno()
        if error in (errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP, errno.ENOTSUP):
            raise RuntimeError("Atomic no-replace rename unsupported") from OSError(
                error, os.strerror(error))
        raise OSError(error, os.strerror(error), destination)


def rename_directory_noreplace_at(source_parent_fd, source_name,
                                  destination_parent_fd, destination_name):
    """Rename one entry using open parent directories, without overwriting anything.

    Changing a parent path cannot redirect this call. Another program can still
    replace the source entry; the rename does not require a particular inode.
    """
    if sys.platform != "linux":
        raise RuntimeError("Atomic no-replace rename requires Linux")
    for name in (source_name, destination_name):
        if (not isinstance(name, str) or not name or name in (".", "..")
                or "/" in name or chr(92) in name or chr(0) in name):
            raise ValueError("Single safe rename entry name required")
    for fd in (source_parent_fd, destination_parent_fd):
        if type(fd) is not int or fd < 0 or not stat.S_ISDIR(os.fstat(fd).st_mode):
            raise ValueError("Held directory descriptor required")
    _renameat2(source_parent_fd, source_name, destination_parent_fd, destination_name)
