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
