"""No network calls: fake transport tests for redacted Jellyfin shape probe."""

from scripts.sqlite_jellyfin_compat_probe import probe


def test_compatible_sample_reports_aggregate_only():
    def fetch(path, params):
        if path == "/Users":
            return [{"Id": "private-user"}]
        return {"TotalRecordCount": 1, "Items": [{
            "Id": "private-item", "Path": "/private/Media/Title/video.mkv",
            "Tags": ["keep-forever"], "UserData": {
                "IsFavorite": True, "Played": False, "PlayCount": 0,
            },
        }]}
    result = probe(fetch)
    assert result["sampled_items"] == 2
    assert result["item_tags_list"] is True
    assert result["scan_complete"] is False
    assert result["production_authorized"] is False
    assert "private" not in repr(result)
    assert not any(key in result for key in ("users", "items", "paths", "tags"))


def test_missing_user_data_reports_failure_without_exposing_media():
    def fetch(path, params):
        if path == "/Users":
            return [{"Id": "secret"}]
        return {"TotalRecordCount": 1, "Items": [{
            "Id": "item", "Path": "/secret/Title/file.mkv", "Tags": [],
        }]}
    result = probe(fetch)
    assert result["user_data_present"] is False
    assert result["favorite_boolean"] is False
    assert "secret" not in repr(result)


def test_transport_failure_does_not_expose_exception_text():
    def fetch(path, params):
        raise ValueError("token=SECRET")
    result = probe(fetch)
    assert result["request_failed"] is True
    assert "SECRET" not in repr(result)


def test_http_error_reports_status_only():
    import requests

    def fetch(path, params):
        response = requests.Response()
        response.status_code = 401
        response._content = b"secret server details"
        raise requests.HTTPError("private url token", response=response)

    result = probe(fetch)
    assert result["failure_category"] == "http_401"
    assert "secret" not in repr(result)
    assert "private" not in repr(result)


def test_timeout_reports_category_only():
    import requests

    def fetch(path, params):
        raise requests.Timeout("private endpoint")

    result = probe(fetch)
    assert result["failure_category"] == "timeout"
    assert "private" not in repr(result)
