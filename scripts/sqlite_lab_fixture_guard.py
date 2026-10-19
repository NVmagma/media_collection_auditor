"""Read-only guard for a future disposable SQLite move rehearsal.

No files are created, moved, overwritten, or deleted by this module.
"""
from __future__ import annotations

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
