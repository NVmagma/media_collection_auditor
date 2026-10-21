"""Live-only race checks around fresh collection after full content hashing.

Metadata never replaces a content digest or supplies restart authority. These
checks bind earlier hash observations to a fresh protection window while the
same descriptors are held. They do not exclude external writers.
"""
import os
import stat

from app.sqlite_disposable_copy_stage import FLAGS, _directory_names, _identity


def _metadata_snapshot(directory_fd, prefix=""):
    before = _identity(os.fstat(directory_fd))
    observed = {prefix: before}
    names = _directory_names(directory_fd)
    for name in names:
        relative = prefix + name
        info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise RuntimeError("Live copy verification refuses symlinks and special files")
        flags = FLAGS if stat.S_ISDIR(info.st_mode) else os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        fd = os.open(name, flags, dir_fd=directory_fd)
        try:
            if _identity(os.fstat(fd)) != _identity(info):
                raise RuntimeError("Live copy entry changed during metadata verification")
            if stat.S_ISDIR(info.st_mode):
                observed.update(_metadata_snapshot(fd, relative + "/"))
            else:
                observed[relative] = _identity(info)
            if _identity(os.fstat(fd)) != _identity(info):
                raise RuntimeError("Live copy entry changed during metadata verification")
            if _identity(os.stat(name, dir_fd=directory_fd, follow_symlinks=False)) != _identity(info):
                raise RuntimeError("Live copy entry binding changed during metadata verification")
        finally:
            os.close(fd)
    if _directory_names(directory_fd) != names or _identity(os.fstat(directory_fd)) != before:
        raise RuntimeError("Live copy directory changed during metadata verification")
    return observed


def verify_hashed_metadata(trees):
    """Compare whole-tree metadata with the exact observations from hashing."""
    for directory_fd, hashed_metadata in trees:
        if _metadata_snapshot(directory_fd) != hashed_metadata:
            raise RuntimeError("Live copy metadata changed since content verification")


def refresh_hashed_copy(*, trees, refresh, check_window):
    """Collect fresh protections, reject intervening changes, enforce deadline."""
    refresh()
    verify_hashed_metadata(trees)
    check_window()
