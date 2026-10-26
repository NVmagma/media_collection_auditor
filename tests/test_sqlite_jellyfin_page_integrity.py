"""Read-only adversarial pagination and path-integrity tests."""

from datetime import datetime

import pytest

from app.sqlite_jellyfin_collection import collect_title_observation

NOW = datetime(2026, 10, 20, 12)


def item(path="/media/Movies/Movie/file.mkv"):
    return {"Id": "same", "Path": path, "Tags": [],
            "UserData": {"IsFavorite": False, "Played": False, "PlayCount": 0}}


def collect(fetch, folder="Movie"):
    return collect_title_observation(
        fetch=fetch, jellyfin_type="Movie", folder=folder,
        media_key="Movies/Movie", now=NOW, page_size=1)


def transport(*, offset=None, path="/media/Movies/Movie/file.mkv"):
    def fetch(endpoint, params):
        if endpoint == "/Users":
            return [{"Id": "u1"}]
        return {"TotalRecordCount": 1, "StartIndex": (
            params["StartIndex"] if offset is None else offset),
            "Items": [item(path)]}
    return fetch


def test_matching_response_offset_remains_advisory():
    assert collect(transport())["status"] == "shape_valid_untrusted"


def test_incorrect_response_offset_fails_closed():
    result = collect(transport(offset=1))
    assert "jellyfin_collection_incomplete" in result["blockers"]
    assert result["signals"] is None


@pytest.mark.parametrize("path", [
    "/media/Movies/Movie/../Movie/file.mkv",
    "/media//Movies/Movie/file.mkv",
    "/media/Movies/Movie/./file.mkv",
    "/media/Movies/Movie\\file.mkv",
])
def test_noncanonical_paths_fail_closed(path):
    result = collect(transport(path=path))
    assert result["status"] == "blocked"
    assert result["signals"] is None


@pytest.mark.parametrize("folder", ["../Movie", "Movie/Other", ".", "..", "Movie\\Other"])
def test_folder_is_single_component(folder):
    with pytest.raises(ValueError):
        collect(transport(), folder=folder)
