"""Multi-user and season protection coverage, using only mocked HTTP."""

import pytest

from app.sqlite_recovery_http import ReadOnlyRecoveryHTTP


class Response:
    def __init__(self, value):
        self.value = value

    def raise_for_status(self):
        pass

    def json(self):
        return self.value


class HTTP:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def get(self, url, *, headers, timeout):
        self.calls.append(url)
        if url not in self.mapping:
            raise RuntimeError("Unexpected test URL")
        return Response(self.mapping[url])


BASE = "http://jellyfin:8096"


def item(title, tags=(), favorite=False):
    return {"Id": title, "Tags": list(tags), "UserData": {"IsFavorite": favorite}}


def client(mapping):
    http = HTTP(mapping)
    return ReadOnlyRecoveryHTTP(
        jellyfin_url=BASE, jellyfin_token="token",
        jellyfin_user_id="user1", http=http,
    ), http


def test_aggregates_other_users_favorites_and_season_tags():
    mapping = {
        BASE + "/Users": [{"Id": "user1"}, {"Id": "user2"}],
        BASE + "/Users/user1/Items/show": item("show"),
        BASE + "/Users/user1/Items/season1": item("season1"),
        BASE + "/Users/user2/Items/show": item("show", favorite=True),
        BASE + "/Users/user2/Items/season1": item("season1", ["KEEP-FOREVER"]),
    }
    adapter, http = client(mapping)
    report = adapter.jellyfin_fetch_all_users("show", season_ids=("season1",))
    assert report["data"]["favorite"] is True
    assert report["data"]["keep_forever"] is True
    assert report["data"]["complete"] is False
    assert len(http.calls) == 5


def test_unprotected_multiuser_evidence_still_incomplete():
    mapping = {
        BASE + "/Users": [{"Id": "user1"}],
        BASE + "/Users/user1/Items/movie": item("movie"),
    }
    adapter, _ = client(mapping)
    report = adapter.jellyfin_fetch_all_users("movie")
    assert report["data"]["keep"] is False
    assert report["data"]["complete"] is False


@pytest.mark.parametrize("users", [
    [], [{"Id": "user1"}, {"Id": "user1"}], [{"Id": "../bad"}],
])
def test_user_enumeration_must_be_nonempty_unique_and_safe(users):
    adapter, _ = client({BASE + "/Users": users})
    with pytest.raises(RuntimeError):
        adapter.jellyfin_fetch_all_users("show")


def test_missing_season_response_blocks_instead_of_guessing():
    mapping = {
        BASE + "/Users": [{"Id": "user1"}],
        BASE + "/Users/user1/Items/show": item("show"),
        BASE + "/Users/user1/Items/season1": {"Id": "season1", "Tags": []},
    }
    adapter, _ = client(mapping)
    with pytest.raises(RuntimeError, match="favorite unavailable"):
        adapter.jellyfin_fetch_all_users("show", season_ids=("season1",))


def test_duplicate_seasons_rejected_before_http():
    adapter, http = client({})
    with pytest.raises(RuntimeError, match="season identity"):
        adapter.jellyfin_fetch_all_users("show", season_ids=("season1", "season1"))
    assert http.calls == []
