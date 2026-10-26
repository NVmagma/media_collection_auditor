"""Live-probe logic tested with disposable SQLite and fake transport."""
from datetime import datetime
import json

import pytest

from app.sqlite_jellyfin_coverage_probe import probe_coverage
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from scripts.sqlite_jellyfin_tracked_coverage import main

NOW = datetime(2026, 10, 1, 12)


def db(tmp_path, keys):
    state = {section: {} for section in SECTIONS}
    state["first_seen"] = {key: "2026-09-01T12:00:00" for key in keys}
    path = tmp_path / "lab.db"
    write_offline_snapshot(state, path)
    return path


def item(name, kind="Movie", tags=None):
    return {"Id": name, "Type": kind,
            "Path": "/media/" + name + ("/movie.mkv" if kind == "Movie" else ""),
            "Tags": tags or [],
            "UserData": {"Played": False, "PlayCount": 0, "IsFavorite": False}}


def transport(records, calls):
    def fetch(path, params):
        calls.append((path, params))
        if path == "/Users":
            return [{"Id": "private-user"}]
        items = records[params["IncludeItemTypes"]]
        start = params["StartIndex"]
        return {"TotalRecordCount": len(items), "Items": items[start:start + params["Limit"]]}
    return fetch


def test_single_scan_shared_across_titles_and_summary_has_no_identifiers(tmp_path):
    path = db(tmp_path, ["SecretMovie", "Other", "TV/PrivateShow"])
    before = path.read_bytes()
    calls = []
    report = probe_coverage(path, transport({
        "Movie": [item("SecretMovie", tags=["keep-forever"]), item("Other")],
        "Series": [item("PrivateShow", "Series")],
    }, calls), now=NOW)
    assert report["coverage_complete"] is True
    assert report["covered_titles"] == 3
    assert len(calls) == report["request_count"] == 3
    assert report["production_authorized"] is False
    assert report["freshness_independently_verified"] is False
    assert path.read_bytes() == before
    output = json.dumps(report)
    assert all(value not in output for value in ["SecretMovie", "PrivateShow", "private-user", "/media/"])


def test_unsupported_key_and_missing_match_block(tmp_path):
    path = db(tmp_path, ["Odd/Key", "Absent"])
    report = probe_coverage(path, transport({"Movie": []}, []), now=NOW)
    assert report["coverage_complete"] is False
    assert report["blocked_titles"] == 2
    assert report["blocker_counts"]["jellyfin_title_request_missing"] == 1
    assert report["blocker_counts"]["jellyfin_title_unmatched"] == 1


def test_transport_failure_is_cached_and_never_leaked(tmp_path):
    path = db(tmp_path, ["One", "Two"])
    calls = []
    def fetch(endpoint, params):
        calls.append(endpoint)
        if endpoint == "/Users":
            return [{"Id": "user"}]
        raise RuntimeError("sensitive-token")
    report = probe_coverage(path, fetch, now=NOW)
    assert len(calls) == 2
    assert report["blocked_titles"] == 2
    assert "sensitive-token" not in json.dumps(report)


def test_missing_database_never_created_or_queried(tmp_path):
    path = tmp_path / "missing.db"
    with pytest.raises(RuntimeError):
        probe_coverage(path, lambda *args: pytest.fail("unexpected network"), now=NOW)
    assert not path.exists()


def test_pages_cached_without_dropping_later_titles(tmp_path):
    path = db(tmp_path, ["Movie0", "Movie100"])
    calls = []
    report = probe_coverage(path, transport({"Movie": [item("Movie" + str(i)) for i in range(101)]}, calls), now=NOW)
    assert report["covered_titles"] == 2
    assert len(calls) == 3


def test_cli_failure_output_is_sanitized(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("JELLYFIN_HOST_URL", "http://jellyfin.invalid")
    monkeypatch.setenv("JELLYFIN_API_TOKEN", "secret")
    monkeypatch.setattr("sys.argv", ["probe", "--database", str(tmp_path / "missing.db")])
    assert main() == 1
    output = capsys.readouterr().out
    assert "secret" not in output
    assert str(tmp_path) not in output
    assert json.loads(output)["failure_category"] == "probe_unavailable"


def test_revision_change_invalidates_all_coverage(tmp_path, monkeypatch):
    import app.sqlite_jellyfin_coverage_probe as module
    path = db(tmp_path, ["One"])
    original = module.preview_with_collected_jellyfin
    def changed(**kwargs):
        result = original(**kwargs)
        result["preview"]["revision"] += 1
        return result
    monkeypatch.setattr(module, "preview_with_collected_jellyfin", changed)
    report = probe_coverage(path, transport({"Movie": [item("One")]}, []), now=NOW)
    assert report["coverage_complete"] is False
    assert report["covered_titles"] == 0
    assert report["blocked_titles"] == 1
    assert report["blocker_counts"]["sqlite_revision_changed"] == 1


@pytest.mark.parametrize("code,category", [(401, "http_error"), (403, "http_error"),
    (404, "http_error"), (500, "http_error"), (302, "redirect_rejected")])
def test_http_diagnostics_count_failed_request_once_without_identifiers(tmp_path, code, category):
    from scripts.sqlite_jellyfin_tracked_coverage import fetch_readonly
    class Response:
        status_code = code
        def json(self):
            pytest.fail("must not parse error bodies")
    class Session:
        def get(self, url, **kwargs):
            assert kwargs["allow_redirects"] is False
            return Response()
    path = db(tmp_path, ["PrivateOne", "PrivateTwo"])
    report = probe_coverage(path, lambda endpoint, params: fetch_readonly(
        Session(), "http://private-host", endpoint, params), now=NOW)
    assert report["request_count"] == 1
    assert report["transport_failure_counts"] == {category: 1}
    assert report["http_status_counts"] == {str(code): 1}
    assert report["failure_stages"] == ["users"]
    assert report["blocked_titles"] == 2
    assert report["coverage_complete"] is False
    assert "private-host" not in json.dumps(report)
    assert "PrivateOne" not in json.dumps(report)


@pytest.mark.parametrize("exception,category", [
    ("SSLError", "tls_error"), ("Timeout", "timeout"),
    ("ConnectionError", "connection_error"), ("RequestException", "request_error"),
])
def test_transport_exceptions_never_echo_sensitive_text(exception, category):
    import requests
    from app.sqlite_jellyfin_coverage_probe import CoverageFetchError
    from scripts.sqlite_jellyfin_tracked_coverage import fetch_readonly
    class Session:
        def get(self, *args, **kwargs):
            raise getattr(requests.exceptions, exception)("sensitive-token")
    with pytest.raises(CoverageFetchError) as error:
        fetch_readonly(Session(), "http://private-host", "/Users", None)
    assert error.value.category == category
    assert "sensitive-token" not in str(error.value)


def test_invalid_json_is_reported_without_response_body():
    from app.sqlite_jellyfin_coverage_probe import CoverageFetchError
    from scripts.sqlite_jellyfin_tracked_coverage import fetch_readonly
    class Response:
        status_code = 200
        def json(self):
            raise ValueError("sensitive-response")
    class Session:
        def get(self, *args, **kwargs):
            return Response()
    with pytest.raises(CoverageFetchError) as error:
        fetch_readonly(Session(), "http://private-host", "/Users", None)
    assert error.value.category == "invalid_json"
    assert "sensitive-response" not in str(error.value)


def test_live_summary_counts_titles_once_across_users(tmp_path):
    path = db(tmp_path, ["One"])
    before = path.read_bytes()
    def fetch(endpoint, params):
        if endpoint == "/Users":
            return [{"Id": "u1"}, {"Id": "u2"}]
        record = item("One", tags=["keep-forever", "keep"])
        record["UserData"]["IsFavorite"] = True
        return {"TotalRecordCount": 1, "Items": [record]}
    result = probe_coverage(path, fetch, now=NOW)
    assert result["protection_summary"] == {
        "available": True,
        "counts": {"protected": 1, "keep_all": 1, "keep": 1, "favorite": 1},
    }
    assert path.read_bytes() == before
    assert "One" not in json.dumps(result)
    assert result["production_authorized"] is False


def test_revision_change_makes_protection_unknown(tmp_path, monkeypatch):
    import app.sqlite_jellyfin_coverage_probe as module
    path = db(tmp_path, ["One"])
    original = module.preview_with_collected_jellyfin
    def changed(**kwargs):
        result = original(**kwargs)
        result["preview"]["revision"] += 1
        return result
    monkeypatch.setattr(module, "preview_with_collected_jellyfin", changed)
    report = probe_coverage(path, transport({"Movie": [item("One", tags=["keep-forever"])]}, []), now=NOW)
    assert report["protection_summary"]["available"] is False
    assert all(value is None for value in report["protection_summary"]["counts"].values())
