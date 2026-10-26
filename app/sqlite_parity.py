"""Offline read-only comparison of JSON and experimental SQLite tracking.

No database creation, state migration, or lifecycle decisions are performed.
"""
from __future__ import annotations

from pathlib import Path

from app.sqlite_json import parse_unique_json
from app.sqlite_state import SECTIONS, read_snapshot, validate_snapshot


def compare_tracking_snapshots(json_path: Path, sqlite_path: Path) -> dict:
    """Compare complete snapshots without exposing media keys or values."""
    try:
        original = parse_unique_json(Path(json_path).read_bytes())
        if not isinstance(original, dict):
            raise RuntimeError("JSON state is not an object")
        original = dict(original)
        for section in SECTIONS:
            original.setdefault(section, {})
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
