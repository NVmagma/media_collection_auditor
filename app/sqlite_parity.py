"""Offline read-only comparison of JSON and experimental SQLite tracking.

No database creation, state migration, or lifecycle decisions are performed.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.sqlite_state import SECTIONS, read_snapshot, validate_snapshot


def compare_tracking_snapshots(json_path: Path, sqlite_path: Path) -> dict:
    """Compare complete snapshots without exposing media keys or values."""
    try:
        with Path(json_path).open("r", encoding="utf-8") as handle:
            original = json.load(handle)
        validate_snapshot(original)
        converted = read_snapshot(sqlite_path)
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        return {"status": "blocked", "authorization": "not_authorized",
                "reason": "snapshot_unavailable_or_invalid"}

    if set(original) != set(converted):
        return {"status": "mismatch", "authorization": "not_authorized",
                "reason": "section_mismatch"}
    for section in original:
        if original[section] != converted[section]:
            return {"status": "mismatch", "authorization": "not_authorized",
                    "reason": "state_mismatch",
                    "section": section if section in SECTIONS else "extra_state"}
    return {"status": "match", "authorization": "not_authorized",
            "reason": "offline_snapshot_parity"}
