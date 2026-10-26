"""Injected Jellyfin response compatibility and fail-closed checks."""

from datetime import datetime

import pytest

from app.sqlite_jellyfin_collection import collect_title_observation

NOW = datetime(2026, 10, 20, 12)


def movie(**overrides):
    value = {"Id": "movie-1", "Path": "/media/Movies/Movie/file.mkv",
             "Type": "Movie", "Tags": [],
             "UserData": {"Played": False, "PlayCount": 0, "IsFavorite": False}}
    value.update(overrides)
    return value


def collect(fetch, page_size=2):
    return collect_title_observation(
        fetch=fetch, jellyfin_type="Movie", folder="Movie",
        media_key="Movies/Movie", now=NOW, page_size=page_size)


def response(items, total=None):
    def fetch(path, params):
        if path == "/Users":
            return [{"Id": "u1"}]
        return {"TotalRecordCount": len(items) if total is None else total,
                "Items": items[params["StartIndex"]:params["StartIndex"] + params["Limit"]]}
    return fetch


def test_optional_matching_type_is_accepted():
    assert collect(response([movie()]))["status"] == "shape_valid_untrusted"


def test_absent_type_is_accepted_for_existing_api_shape():
    item = movie()
    item.pop("Type")
    assert collect(response([item]))["status"] == "shape_valid_untrusted"


@pytest.mark.parametrize("data", [
    {"Played": False, "PlayCount": 0},
    {"Played": False, "PlayCount": 0, "IsFavorite": None},
    {"Played": False, "PlayCount": -1, "IsFavorite": False},
    {"Played": False, "PlayCount": True, "IsFavorite": False},
])
def test_incomplete_or_invalid_user_data_blocks(data):
    result = collect(response([movie(UserData=data)]))
    assert result["status"] == "blocked"
    assert result["signals"] is None


def test_wrong_item_type_blocks():
    result = collect(response([movie(Type="Series")]))
    assert "jellyfin_collection_incomplete" in result["blockers"]


def test_short_nonterminal_page_blocks_even_with_total_metadata():
    result = collect(response([movie()], total=3), page_size=2)
    assert "jellyfin_collection_incomplete" in result["blockers"]


def test_exact_final_short_page_is_allowed():
    items = [movie(Id="other", Path="/media/Movies/Other/file.mkv"),
             movie(Id="other-2", Path="/media/Movies/Other2/file.mkv"),
             movie()]
    assert collect(response(items), page_size=2)["status"] == "shape_valid_untrusted"


def test_empty_result_cannot_establish_unprotected_title():
    result = collect(response([]))
    assert result["status"] == "blocked"
    assert result["signals"] is None
