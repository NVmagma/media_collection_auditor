"""Jellyfin series enumeration is independent, read-only and fail-closed."""

import pytest

from app.sqlite_recovery_http import ReadOnlyRecoveryHTTP

BASE = "http://jellyfin:8096"
SEASONS = BASE + "/Shows/show/Seasons?UserId=user1&StartIndex=0&Limit=10000"


class Response:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class HTTP:
    def __init__(self, seasons, *, second=None):
        self.seasons = seasons
        self.second = second
        self.calls = []
        self.season_calls = 0

    def get(self, url, *, headers, timeout):
        self.calls.append(url)
        if url == SEASONS:
            self.season_calls += 1
            return Response(
                self.second if self.season_calls == 2 and self.second is not None
                else self.seasons
            )
        if url == BASE + "/Users":
            return Response([{"Id": "user1"}, {"Id": "user2"}])
        if url.endswith("/Items/show"):
            return Response({"Id": "show", "Tags": [], "UserData": {"IsFavorite": False}})
        if url.endswith("/Items/season1"):
            return Response({
                "Id": "season1",
                "Tags": ["keep-forever"] if "/user2/" in url else [],
                "UserData": {"IsFavorite": False},
            })
        raise RuntimeError("Unexpected HTTP request")


def adapter(http):
    return ReadOnlyRecoveryHTTP(
        jellyfin_url=BASE, jellyfin_token="secret",
        jellyfin_user_id="user1", http=http,
    )


def listing(items, total=None):
    return {
        "Items": items,
        "TotalRecordCount": len(items) if total is None else total,
    }


def test_enumerates_and_rechecks_all_seasons_and_users():
    http = HTTP(listing([{"Id": "season1", "SeriesId": "show"}]))
    report = adapter(http).jellyfin_fetch_verified_series("show")
    assert report["data"]["keep_forever"] is True
    assert report["data"]["complete"] is False
    assert http.season_calls == 2
    assert http.calls.count(SEASONS) == 2


@pytest.mark.parametrize("response", [
    listing([{"Id": "season1", "SeriesId": "show"}], total=2),
    listing([{"Id": "season1", "SeriesId": "wrong"}]),
    listing([{"Id": "season1", "SeriesId": "show"}] * 2),
    {"Items": [], "TotalRecordCount": True},
])
def test_partial_wrong_owner_or_duplicate_seasons_rejected(response):
    http = HTTP(response)
    with pytest.raises(RuntimeError):
        adapter(http).jellyfin_fetch_verified_series("show")


def test_changed_season_set_blocks_after_protection_reads():
    first = listing([{"Id": "season1", "SeriesId": "show"}])
    second = listing([])
    http = HTTP(first, second=second)
    with pytest.raises(RuntimeError, match="changed"):
        adapter(http).jellyfin_fetch_verified_series("show")
    assert http.season_calls == 2


def test_empty_series_is_not_mistaken_for_complete_protection():
    http = HTTP(listing([]))
    report = adapter(http).jellyfin_fetch_verified_series("show")
    assert report["data"]["complete"] is False
