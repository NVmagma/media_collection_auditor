"""Mocked HTTP contract tests; no network, production state or media."""

import pytest

from app.sqlite_recovery_http import ReadOnlyRecoveryHTTP


class Response:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class FakeHTTP:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def get(self, url, *, headers, timeout):
        self.calls.append((url, headers, timeout))
        return Response(self.data)


def adapter(http):
    return ReadOnlyRecoveryHTTP(
        jellyfin_url="http://jellyfin:8096", jellyfin_token="secret",
        jellyfin_user_id="user1", radarr_url="http://radarr:7878",
        radarr_key="radarr-secret", sonarr_url="http://sonarr:8989",
        sonarr_key="sonarr-secret", http=http,
    )


def test_jellyfin_read_only_protection_is_explicitly_incomplete():
    http = FakeHTTP({
        "Id": "film1", "Tags": ["KEEP-FOREVER"],
        "UserData": {"IsFavorite": False},
    })
    result = adapter(http).jellyfin_fetch("film1")
    assert result["data"]["keep_forever"] is True
    assert result["data"]["complete"] is False
    assert http.calls == [(
        "http://jellyfin:8096/Users/user1/Items/film1",
        {"X-Emby-Token": "secret"}, 15,
    )]


@pytest.mark.parametrize("data", [
    {"Id": "wrong", "Tags": [], "UserData": {"IsFavorite": False}},
    {"Id": "film1", "Tags": None, "UserData": {"IsFavorite": False}},
    {"Id": "film1", "Tags": [], "UserData": {}},
])
def test_jellyfin_invalid_or_missing_evidence_blocks(data):
    with pytest.raises(RuntimeError):
        adapter(FakeHTTP(data)).jellyfin_fetch("film1")


def test_arr_exact_record_is_read_only():
    http = FakeHTTP({"id": 17, "path": "/media/Movies/Movie", "monitored": True})
    result = adapter(http).arr_fetch("radarr", 17)
    assert result["title_id"] == "17"
    assert http.calls == [(
        "http://radarr:7878/api/v3/movie/17",
        {"X-Api-Key": "radarr-secret"}, 15,
    )]


@pytest.mark.parametrize("service, title_id, data", [
    ("radarr", 17, {"id": 18}),
    ("sonarr", 17, {"id": "17"}),
    ("other", 17, {"id": 17}),
    ("radarr", True, {"id": True}),
])
def test_arr_wrong_identity_blocks(service, title_id, data):
    with pytest.raises(RuntimeError):
        adapter(FakeHTTP(data)).arr_fetch(service, title_id)


def test_path_injection_rejected_without_http_call():
    http = FakeHTTP({})
    with pytest.raises(RuntimeError, match="identity"):
        adapter(http).jellyfin_fetch("../admin")
    assert http.calls == []


def test_missing_arr_credentials_fail_closed():
    http = FakeHTTP({"id": 17})
    client = ReadOnlyRecoveryHTTP(
        jellyfin_url="http://jellyfin", jellyfin_token="secret",
        jellyfin_user_id="user1", radarr_url="http://radarr", http=http,
    )
    with pytest.raises(RuntimeError, match="credentials"):
        client.arr_fetch("radarr", 17)
    assert http.calls == []
