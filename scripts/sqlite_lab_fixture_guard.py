"""Read-only guard for a future disposable SQLite move rehearsal.

No files are created, moved, overwritten, or deleted by this module.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat

FIXTURE_NAMES = (
    "sqlite_disposable_move_source.bin",
    "sqlite_disposable_move_destination.bin",
    "sqlite_disposable_move_state.db",
)


def validate_disposable_lab(lab: Path = Path("/lab")) -> dict[str, Path]:
    """Reject unsafe or occupied fixture paths before any future lab action."""
    if not isinstance(lab, Path) or not lab.is_absolute() or lab.name != "lab":
        raise RuntimeError("Dedicated /lab mount required")
    if lab != Path("/lab"):
        raise RuntimeError("Only /lab is permitted")
    if lab.is_symlink() or not lab.is_dir() or os.path.ismount(lab) is False:
        raise RuntimeError("Dedicated mounted lab directory required")
    entries = list(lab.iterdir())
    if entries:
        raise RuntimeError("Lab must be empty before fixture preparation")
    return {name: lab / name for name in FIXTURE_NAMES}


def validate_fixture_slot(path: Path, lab: Path = Path("/lab")) -> None:
    """Verify one expected name has no existing object or symlink."""
    if path.parent != lab or path.name not in FIXTURE_NAMES:
        raise RuntimeError("Unexpected fixture path")
    try:
        os.lstat(path)
    except FileNotFoundError:
        return
    raise RuntimeError("Fixture path already occupied")


def inspect_disposable_fixture(path: Path, lab: Path = Path("/lab")) -> dict[str, str]:
    """Read-only, fail-closed inspection of one already-created fixture.

    This is local metadata only: it cannot establish identity across a move
    or authorize recovery. Reject symlinks, directories and hard-linked files.
    """
    if path.parent != lab or path.name not in FIXTURE_NAMES[:2]:
        return {"status": "blocked", "reason": "unexpected_fixture_path"}
    try:
        metadata = os.lstat(path)
    except OSError:
        return {"status": "blocked", "reason": "fixture_unavailable"}
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        return {"status": "blocked", "reason": "fixture_not_isolated_regular_file"}
    return {"status": "observed_unverified", "reason": "local_metadata_only"}


def verify_disposable_fixture_digest(
    path: Path, expected_sha256: str, lab: Path = Path("/lab")
) -> dict[str, str]:
    """Check bounded disposable bytes; never authorize recovery.

    A matching digest is local, untrusted evidence only. O_NOFOLLOW and
    descriptor metadata checks prevent following a replaced final symlink.
    """
    if path.parent != lab or path.name not in FIXTURE_NAMES[:2]:
        return {"status": "blocked", "reason": "unexpected_fixture_path"}
    if (not isinstance(expected_sha256, str) or len(expected_sha256) != 64
            or any(char not in "0123456789abcdef" for char in expected_sha256)):
        return {"status": "blocked", "reason": "invalid_expected_digest"}
    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(path, flags)
        try:
            before = os.fstat(fd)
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                    or before.st_size > 1024 * 1024):
                return {"status": "blocked", "reason": "fixture_not_bounded_regular_file"}
            digest = hashlib.sha256()
            remaining = before.st_size
            while remaining:
                block = os.read(fd, min(65536, remaining))
                if not block:
                    return {"status": "blocked", "reason": "fixture_changed_during_read"}
                digest.update(block)
                remaining -= len(block)
            after = os.fstat(fd)
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
                    before.st_ctime_ns, before.st_nlink) != (
                    after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
                    after.st_ctime_ns, after.st_nlink):
                return {"status": "blocked", "reason": "fixture_changed_during_read"}
            if digest.hexdigest() != expected_sha256:
                return {"status": "blocked", "reason": "fixture_digest_mismatch"}
            return {"status": "observed_unverified", "reason": "local_digest_matches"}
        finally:
            os.close(fd)
    except OSError:
        return {"status": "blocked", "reason": "fixture_unavailable"}


def inspect_lab_mount_boundaries(
    mountinfo: str, lab: Path = Path("/lab")
) -> dict[str, str]:
    """Conservatively inspect Linux mountinfo; never authorize operations."""
    import re

    if lab != Path("/lab"):
        return {"status": "blocked", "reason": "unexpected_lab_path"}
    if not isinstance(mountinfo, str) or not mountinfo.strip():
        return {"status": "blocked", "reason": "mountinfo_unavailable"}
    observations = []
    for line in mountinfo.splitlines():
        halves = line.split(" - ")
        if len(halves) != 2:
            return {"status": "blocked", "reason": "mountinfo_malformed"}
        fields, trailing = halves[0].split(), halves[1].split()
        if (len(fields) < 6 or len(trailing) < 3
                or not fields[0].isascii() or not fields[0].isdecimal()
                or not fields[1].isascii() or not fields[1].isdecimal()
                or re.fullmatch(r"[0-9]+:[0-9]+", fields[2]) is None):
            return {"status": "blocked", "reason": "mountinfo_malformed"}
        root, mount_point = fields[3], fields[4]
        if "\\" in root or "\\" in mount_point:
            return {"status": "blocked", "reason": "mountinfo_escaped_path_unverified"}
        if any(not os.path.isabs(v) or os.path.normpath(v) != v
               or any(part in (".", "..") for part in v.split("/"))
               for v in (root, mount_point)):
            return {"status": "blocked", "reason": "mountinfo_malformed"}
        if mount_point == "/lab" or mount_point.startswith("/lab/"):
            observations.append((mount_point, root))
    if len([point for point, _ in observations if point == "/lab"]) != 1:
        return {"status": "blocked", "reason": "lab_mount_missing_or_ambiguous"}
    if any(point != "/lab" for point, _ in observations):
        return {"status": "blocked", "reason": "nested_lab_mount"}
    if observations[0][1] != "/":
        return {"status": "blocked", "reason": "lab_mount_root_unverified"}
    return {"status": "observed_unverified", "reason": "mount_layout_only"}
