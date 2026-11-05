"""Duplicate JSON keys must never be silently discarded."""

import pytest

from app.json_validation import parse_unique_json


@pytest.mark.parametrize("raw", [
    b'{"queued": {}, "queued": {}}',
    b'{"arr_sync_pending": {"item": {"stage": "keep", "stage": "holding"}}}',
    b'{"arr_sync_pending": {"item": {}, "item": {}}}',
])
def test_strict_parser_rejects_duplicate_keys_at_any_depth(raw):
    with pytest.raises(ValueError, match="Duplicate JSON key"):
        parse_unique_json(raw)

