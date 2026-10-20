"""Linux-only atomic no-replace rename for isolated SQLite rehearsals.

Never fall back to os.rename: preflight absence is vulnerable to races.
Unsupported kernels/filesystems fail closed with the intent still persisted.
"""

from __future__ import annotations

import ctypes
import errno
import os
from pathlib import Path
import sys

_AT_FDCWD = -100
_RENAME_NOREPLACE = 1


def rename_directory_noreplace(source: str | Path, destination: str | Path) -> None:
    """Atomically rename without overwriting an unexpectedly created target."""
    if sys.platform != "linux":
        raise RuntimeError("Atomic no-replace rename requires Linux")
    source, destination = os.fspath(source), os.fspath(destination)
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise RuntimeError("renameat2 unavailable; refusing unsafe fallback")
    renameat2.argtypes = [
        ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
        ctypes.c_char_p, ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    rc = renameat2(_AT_FDCWD, os.fsencode(source),
                   _AT_FDCWD, os.fsencode(destination), _RENAME_NOREPLACE)
    if rc != 0:
        error = ctypes.get_errno()
        if error in (errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP, errno.ENOTSUP):
            raise RuntimeError("Atomic no-replace rename unsupported") from OSError(
                error, os.strerror(error))
        raise OSError(error, os.strerror(error), destination)
