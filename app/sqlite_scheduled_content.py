"""Bounded, descriptor-held TV content observation; no clocks or files written.

Match the existing newest-content policy (files and nested directories), while
rejecting incomplete reads, symlinks and observed changes instead of ignoring
errors. This detects changes, not writer exclusion or a stable future snapshot.
"""
from datetime import datetime
import math
import os
import stat
from time import monotonic

from app.sqlite_scheduled_paths import _canonical, _open_directory


class ScheduledContentBlocked(RuntimeError):
    pass


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def observe_scheduled_content(*, title_path, now, maximum_entries=100000,
                              maximum_depth=64, maximum_seconds=30, timer=monotonic):
    """Return newest naive local descendant mtime, or None for an empty title.

    A failure returns no timestamp. Callers must block that title's reset/move,
    never treat unreadable content as absent or fall back to its old clock.
    No follow-up stat resolves a stored path after releasing the descriptors.
    """
    _canonical(title_path)
    if (not isinstance(now, datetime) or now.tzinfo is not None
            or type(maximum_entries) is not int or not 1 <= maximum_entries <= 1000000
            or type(maximum_depth) is not int or not 0 <= maximum_depth <= 64
            or type(maximum_seconds) not in (int, float)
            or not math.isfinite(maximum_seconds) or maximum_seconds <= 0):
        raise ValueError('Bounded content observation policy required')
    started = timer(); count = 0; newest = None
    def check_time():
        elapsed = timer() - started
        if not math.isfinite(elapsed) or not 0 <= elapsed < maximum_seconds:
            raise ScheduledContentBlocked('content_deadline_exceeded')
    def entries(fd, *, count_entries):
        nonlocal count
        result = {}
        with os.scandir(fd) as iterator:
            for entry in iterator:
                check_time()
                if count_entries:
                    count += 1
                    if count > maximum_entries:
                        raise ScheduledContentBlocked('content_entry_limit_exceeded')
                if len(result) >= maximum_entries:
                    raise ScheduledContentBlocked('content_entry_limit_exceeded')
                info = entry.stat(follow_symlinks=False)
                if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                    raise ScheduledContentBlocked('unsupported_content_entry')
                result[entry.name] = info
        return result
    def walk(fd, depth):
        nonlocal newest
        check_time()
        before = _identity(os.fstat(fd))
        observed = entries(fd, count_entries=True)
        for name, info in observed.items():
            check_time()
            timestamp = datetime.fromtimestamp(info.st_mtime)
            if timestamp > now:
                raise ScheduledContentBlocked('future_content_timestamp')
            newest = timestamp if newest is None else max(newest, timestamp)
            if stat.S_ISDIR(info.st_mode):
                if depth >= maximum_depth:
                    raise ScheduledContentBlocked('content_depth_limit_exceeded')
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                dir_fd=fd)
                try:
                    if _identity(os.fstat(child)) != _identity(info):
                        raise ScheduledContentBlocked('content_entry_changed')
                    walk(child, depth + 1)
                finally:
                    os.close(child)
        check_time()
        after = entries(fd, count_entries=False)
        if (_identity(os.fstat(fd)) != before
                or {name: _identity(info) for name, info in observed.items()} !=
                   {name: _identity(info) for name, info in after.items()}):
            raise ScheduledContentBlocked('content_changed_during_observation')
    fd = None
    try:
        check_time()
        fd = _open_directory(title_path)
        held_identity = _identity(os.fstat(fd))
        walk(fd, 0)
        reopened = _open_directory(title_path)
        try:
            if _identity(os.fstat(reopened)) != held_identity:
                raise ScheduledContentBlocked('title_path_changed')
        finally:
            os.close(reopened)
        check_time()
        return newest
    except OSError:
        raise ScheduledContentBlocked('content_unavailable_or_changed') from None
    finally:
        if fd is not None:
            os.close(fd)
