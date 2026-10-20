"""Adversarial title identity and pagination checks."""

from datetime import datetime

from app.sqlite_jellyfin_collection import collect_title_observation

NOW = datetime(2026, 10, 20, 12)


def item(identity, path="/media/Movies/Movie/file.mkv"):
    return {"Id": identity, "Path": path, "Tags": [],
            "UserData": {"IsFavorite": False, "Played": False, "PlayCount": 0}}


def collect(fetch):
    return collect_title_observation(
        fetch=fetch, jellyfin_type="Movie", folder="Movie",
        media_key="Movies/Movie", now=NOW, page_size=1)


def test_different_item_ids_same_folder_are_ambiguous():
    def fetch(path, params):
        if path == "/Users":
            return [{"Id": "u1"}, {"Id": "u2"}]
        identity = "one" if "/u1/" in path else "two"
        return {"TotalRecordCount": 1, "Items": [item(identity)]}
    result = collect(fetch)
    assert "jellyfin_title_ambiguous" in result["blockers"]
    assert result["signals"] is None


def test_changed_total_between_pages_blocks():
    def fetch(path, params):
        if path == "/Users":
            return [{"Id": "u1"}]
        if params["StartIndex"] == 0:
            return {"TotalRecordCount": 2, "Items": [item("one")]}
        return {"TotalRecordCount": 1, "Items": []}
    result = collect(fetch)
    assert "jellyfin_collection_incomplete" in result["blockers"]
    assert result["signals"] is None


def test_repeated_item_across_users_is_not_ambiguous():
    def fetch(path, params):
        if path == "/Users":
            return [{"Id": "u1"}, {"Id": "u2"}]
        return {"TotalRecordCount": 1, "Items": [item("same")]}
    result = collect(fetch)
    assert result["status"] == "shape_valid_untrusted"
    assert result["authorization"] == "not_authorized"


def test_different_paths_same_item_id_are_ambiguous():
    def fetch(path, params):
        if path == "/Users":
            return [{"Id": "u1"}, {"Id": "u2"}]
        path_value = ("/media/Movies/Movie/file.mkv" if "/u1/" in path
                      else "/other/Movies/Movie/file.mkv")
        return {"TotalRecordCount": 1, "Items": [item("same", path_value)]}
    result = collect(fetch)
    assert "jellyfin_title_ambiguous" in result["blockers"]
