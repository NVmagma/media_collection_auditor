"""Offline contract tests for full Jellyfin scan; no network or media changes."""
from scripts.sqlite_jellyfin_full_scan import scan


def item(i):
    return {
        "Id": f"secret-{i}", "Path": f"/private/secret-{i}/video.mkv",
        "Tags": ["keep-forever"], "Type": "Movie",
        "UserData": {"IsFavorite": False, "Played": False, "PlayCount": 0},
    }


def fake_fetch(path, params):
    if path == "/Users":
        return [{"Id": "private-user"}]
    kind = params["IncludeItemTypes"]
    start = params["StartIndex"]
    if kind == "Series":
        return {"TotalRecordCount": 0, "Items": [], "StartIndex": start}
    return {
        "TotalRecordCount": 102,
        "StartIndex": start,
        "Items": [item(i) for i in range(start, min(start + 100, 102))],
    }


def test_full_scan_multiple_pages_redacted():
    result = scan(fake_fetch)
    assert result["scan_complete"] is True
    assert result["pages_checked"] == 3
    assert result["items_checked"] == 102
    assert result["production_authorized"] is False
    assert "private" not in repr(result)
    assert "secret" not in repr(result)


def test_full_scan_blocks_short_page():
    def fetch(path, params):
        if path == "/Users":
            return [{"Id": "private"}]
        return {"TotalRecordCount": 101, "Items": [item(0)]}
    result = scan(fetch)
    assert result["scan_complete"] is False
    assert result["failure_category"] == "invalid_or_incomplete_response"


def test_full_scan_blocks_duplicate_items():
    def fetch(path, params):
        if path == "/Users":
            return [{"Id": "private"}]
        return {"TotalRecordCount": 2, "Items": [item(0), item(0)]}
    assert scan(fetch)["scan_complete"] is False


def test_full_scan_blocks_missing_protection_data():
    def fetch(path, params):
        if path == "/Users":
            return [{"Id": "private"}]
        bad = item(0)
        del bad["Tags"]
        return {"TotalRecordCount": 1, "Items": [bad]}
    assert scan(fetch)["scan_complete"] is False


def test_full_scan_redacts_network_errors():
    import requests
    def fetch(path, params):
        raise requests.ConnectionError("private-token-secret")
    result = scan(fetch)
    assert result["failure_category"] == "connection_error"
    assert "secret" not in repr(result)


def test_full_scan_rejects_changed_total():
    def fetch(path, params):
        if path == "/Users":
            return [{"Id": "private"}]
        start = params["StartIndex"]
        total = 101 if start == 0 else 102
        return {"TotalRecordCount": total,
                "Items": [item(i) for i in range(start, min(start + 100, total))]}
    assert scan(fetch)["scan_complete"] is False


def test_failure_reason_is_fixed_label_not_exception_text():
    def fetch(path, params):
        if path == "/Users":
            return [{"Id": "private"}]
        return {"TotalRecordCount": 1, "Items": [{"Id": "private"}]}
    result = scan(fetch)
    assert result["validation_failure"] == "item_path"
    assert "private" not in repr(result)


def test_page_length_failure_is_identifiable():
    def fetch(path, params):
        if path == "/Users":
            return [{"Id": "private"}]
        return {"TotalRecordCount": 101, "Items": [item(0)]}
    assert scan(fetch)["validation_failure"] == "page_length"


def test_specific_missing_favorite_is_redacted():
    def fetch(path, params):
        if path == "/Users":
            return [{"Id": "secret-user"}]
        bad = item(0)
        del bad["UserData"]["IsFavorite"]
        return {"TotalRecordCount": 1, "Items": [bad]}
    result = scan(fetch)
    assert result["validation_failure"] == "favorite_field"
    assert "secret" not in repr(result)
    assert result["scan_complete"] is False


def test_specific_bad_path_fails_closed():
    def fetch(path, params):
        if path == "/Users":
            return [{"Id": "secret-user"}]
        bad = item(0)
        bad["Path"] = "/private/../secret/video.mkv"
        return {"TotalRecordCount": 1, "Items": [bad]}
    result = scan(fetch)
    assert result["validation_failure"] == "unsafe_item_path"
    assert result["production_authorized"] is False
