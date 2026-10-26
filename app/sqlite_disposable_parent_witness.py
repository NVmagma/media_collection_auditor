"""Pin stage directory identity across a disposable filesystem move.

This catches parent replacement before reconciliation. It does not prevent
malicious concurrent writers; production still requires stronger isolation.
"""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path


@contextmanager
def pinned_stage_directories(root: Path, stages: tuple[str, ...]):
    handles = {}
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        for stage in stages:
            parent = root / stage
            fd = os.open(parent, flags)
            handles[stage] = fd
            assert_stage_directories_unchanged(root, handles)
        yield handles
    finally:
        for fd in handles.values():
            os.close(fd)


def assert_stage_directories_unchanged(root: Path, handles: dict[str, int]) -> None:
    for stage, fd in handles.items():
        expected = os.fstat(fd)
        current = os.stat(root / stage, follow_symlinks=False)
        if ((expected.st_dev, expected.st_ino) !=
                (current.st_dev, current.st_ino)):
            raise RuntimeError("Disposable stage directory changed during move")
