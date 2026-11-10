"""Read JSON without silently dropping duplicate keys or invalid values."""

from __future__ import annotations

import json
from typing import Any


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key!r}")
        result[key] = value
    return result


def parse_unique_json(raw: bytes) -> Any:
    """Reject duplicate keys, including those in nested JSON objects."""
    return json.loads(raw, object_pairs_hook=_unique_object)
