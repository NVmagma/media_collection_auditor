"""Read-only safety preflight for an isolated Unraid SQLite lab.

No directories are created and no containers are started.
"""
from __future__ import annotations

import os
from pathlib import Path
import re


def check_lab_environment(env: dict[str, str] | None = None) -> Path:
    values = os.environ if env is None else env
    raw = values.get("SQLITE_LAB_DIR", "")
    path = Path(raw)
    if not raw or not path.is_absolute() or not path.is_dir():
        raise RuntimeError("SQLITE_LAB_DIR must be an existing absolute directory")
    if any(component.is_symlink() for component in (path, *path.parents)):
        raise RuntimeError("Lab path must not contain symlinks")
    resolved = path.resolve(strict=True)
    if resolved == Path("/") or len(resolved.parts) < 4:
        raise RuntimeError("Lab path must be a dedicated subdirectory")
    forbidden = {"media", "movies", "tv", "shows", "downloads",
                 "media_collection_auditor", "logs"}
    if any(component.lower() in forbidden for component in resolved.parts):
        raise RuntimeError("Lab path overlaps a known production/media directory")
    if "sqlite_lab" not in resolved.name.lower():
        raise RuntimeError("Lab directory name must include sqlite_lab")
    for key in ("SQLITE_LAB_UID", "SQLITE_LAB_GID"):
        value = values.get(key, "")
        if not value.isascii() or not value.isdecimal() or int(value) == 0:
            raise RuntimeError(f"{key} must be a non-root numeric ID")
    image = values.get("SQLITE_LAB_IMAGE", "")
    if re.fullmatch(r"python:3[.]12-slim@sha256:[a-fA-F0-9]{64}", image) is None:
        raise RuntimeError("SQLITE_LAB_IMAGE must be a reviewed digest reference")
    return resolved


if __name__ == "__main__":
    try:
        location = check_lab_environment()
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"Lab preflight blocked: {exc}") from exc
    print(f"Lab preflight passed: {location}")
