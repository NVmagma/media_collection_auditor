"""Synthetic HTTP transport: exact GETs, authentication, no redirect or replay."""
import json
import pytest
from tests.test_sqlite_isolated_arr_inspection import prepare, record
from app.sqlite_arr_outcome_http import inspect_isolated_arr_http
from app.state_store import GuardedSQLiteStateStore


class Response:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self.data = record() if data is None else data
    def json(self):
        return self.data


class HTTP:
    def __init__(self, response=None):
        self.calls = []
        self.response = response or Response()
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_readback_uses_only_exact_authenticated_gets(tmp_path):
    root, database = prepare(tmp_path)
    before = database.read_bytes()
    http = HTTP()
    result = inspect_isolated_arr_http(root=root, radarr_url="https://arr.invalid/radarr/",
                                      radarr_key="private-key", http=http)
    assert result["observation"] == "matching_record_unverified"
    assert len(http.calls) == 2
    for url, kwargs in http.calls:
        assert url == "https://arr.invalid/radarr/api/v3/movie/42"
        assert kwargs == {"headers": {"X-Api-Key": "private-key"}, "timeout": 15, "allow_redirects": False}
    assert "private-key" not in json.dumps(result) and database.read_bytes() == before


@pytest.mark.parametrize("response", [Response(302), Response(401), Response(500),
    Response(data={"id": 99}), Response(data=[]), Response(data={"id": True})])
def test_failed_or_wrong_identity_response_stops_without_retry(tmp_path, response):
    root, database = prepare(tmp_path)
    before = database.read_bytes()
    http = HTTP(response)
    report = inspect_isolated_arr_http(root=root, radarr_url="https://arr.invalid", radarr_key="key", http=http)
    assert report["observation"] == "readback_unavailable_or_invalid"
    assert len(http.calls) == 1 and database.read_bytes() == before


@pytest.mark.parametrize("url", ["https://user:password@arr.invalid", "https://arr.invalid?token=secret",
    "https://arr.invalid/#secret", "https://arr.invalid/../other", "file:///private", "https://arr.invalid:bad"])
def test_unsafe_endpoint_is_refused_before_network(tmp_path, url):
    root, _ = prepare(tmp_path)
    http = HTTP()
    report = inspect_isolated_arr_http(root=root, radarr_url=url, radarr_key="key", http=http)
    assert not http.calls
    assert report["observation"] == "readback_unavailable_or_invalid"


def test_default_session_disables_environment_proxies_and_closes(tmp_path, monkeypatch):
    import app.sqlite_arr_outcome_http as module
    root, _ = prepare(tmp_path)
    http = HTTP()
    http.trust_env = True
    closed = []
    http.close = lambda: closed.append(True)
    monkeypatch.setattr(module.requests, "Session", lambda: http)
    inspect_isolated_arr_http(root=root, radarr_url="https://arr.invalid", radarr_key="key")
    assert http.trust_env is False and closed == [True]


def test_sonarr_readback_uses_tv_key_and_series_endpoint(tmp_path):
    from app.sqlite_audit_session import RevisionedAuditSession
    from tests.test_sqlite_isolated_arr_runner import KEY
    root, database = prepare(tmp_path)
    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    tv_key = "TV/" + KEY
    session.state["keep_seen"][tv_key] = session.state["keep_seen"].pop(KEY)
    queued = session.state["arr_sync_pending"].pop(KEY)
    queued.update(service="sonarr", title_id=99)
    session.state["arr_sync_pending"][tv_key] = queued
    details = session.state["sqlite_pending_operations"]["details"]
    details.update(service="sonarr", title_id=99, media_key=tv_key)
    session.checkpoint()
    http = HTTP(Response(data=record(id=99)))
    report = inspect_isolated_arr_http(root=root, sonarr_url="https://sonarr.invalid", sonarr_key="key", http=http)
    assert report["observation"] == "matching_record_unverified"
    assert all(url == "https://sonarr.invalid/api/v3/series/99" for url, _ in http.calls)
    assert len(http.calls) == 2
