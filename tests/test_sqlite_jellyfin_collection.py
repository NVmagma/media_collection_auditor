from datetime import datetime

from app.sqlite_jellyfin_collection import collect_title_observation

NOW = datetime(2026, 10, 20, 12)


def item(item_id="item-1", path="/media/Movies/Movie/file.mkv", tags=None,
         favorite=False):
    return {"Id": item_id, "Path": path, "Tags": tags or [],
            "UserData": {"IsFavorite": favorite, "Played": False, "PlayCount": 0}}


def transport(pages, users=None):
    users = users if users is not None else [{"Id": "u1"}, {"Id": "u2"}]
    def fetch(path, params):
        if path == "/Users":
            return users
        uid = path.split("/")[2]
        records = pages[uid]
        start, limit = params["StartIndex"], params["Limit"]
        return {"TotalRecordCount": len(records),
                "Items": records[start:start + limit]}
    return fetch


def collect(fetch, page_size=1):
    return collect_title_observation(
        fetch=fetch, jellyfin_type="Movie", folder="Movie",
        media_key="Movies/Movie", now=NOW, page_size=page_size)


def test_protection_aggregates_across_users_and_pages():
    pages = {"u1": [item("other", "/media/Movies/Other/file.mkv"),
                    item(tags=["keep-forever"])],
             "u2": [item(favorite=True)]}
    result = collect(transport(pages))
    assert result["status"] == "shape_valid_untrusted"
    assert result["signals"]["protected"] is True
    assert result["signals"]["keep_all"] is True
    assert result["signals"]["favorite"] is True
    assert result["authorization"] == "not_authorized"


def test_missing_user_page_blocks():
    def fetch(path, params):
        if path == "/Users":
            return [{"Id": "u1"}, {"Id": "u2"}]
        if "/u2/" in path:
            raise TimeoutError("offline")
        return {"TotalRecordCount": 1, "Items": [item()]}
    result = collect(fetch)
    assert result["status"] == "blocked"
    assert "jellyfin_collection_incomplete" in result["blockers"]
    assert result["signals"] is None


def test_missing_pagination_metadata_blocks():
    def fetch(path, params):
        return [{"Id": "u1"}] if path == "/Users" else {"Items": [item()]}
    assert collect(fetch)["status"] == "blocked"


def test_ambiguous_same_folder_blocks():
    pages = {"u1": [item()], "u2": [item("other-id", "/elsewhere/Movie/file.mkv")]}
    result = collect(transport(pages))
    assert "jellyfin_title_ambiguous" in result["blockers"]


def test_missing_title_blocks():
    pages = {"u1": [item("other", "/media/Movies/Other/file.mkv")],
             "u2": []}
    assert "jellyfin_title_unmatched" in collect(transport(pages))["blockers"]


def test_missing_tags_or_userdata_blocks():
    broken = item()
    broken.pop("Tags")
    pages = {"u1": [broken], "u2": []}
    assert "jellyfin_collection_incomplete" in collect(transport(pages))["blockers"]


def test_empty_users_fail_closed():
    assert collect(transport({}, users=[]))["status"] == "blocked"


def test_duplicate_items_across_pages_fail_closed():
    pages = {"u1": [item(), item()], "u2": []}
    assert collect(transport(pages))["status"] == "blocked"


def test_boxset_does_not_block_valid_movie_or_match_title():
    boxset = item("collection", "/media/Movies/Movie/file.mkv")
    boxset["Type"] = "BoxSet"
    movie = item("real-movie", "/media/Movies/Movie/file.mkv", ["keep-forever"])
    movie["Type"] = "Movie"
    result = collect(transport({"u1": [boxset, movie], "u2": [boxset, movie]}))
    assert result["status"] == "shape_valid_untrusted"
    assert result["signals"]["protected"] is True
    assert result["authorization"] == "not_authorized"


def test_boxset_only_never_counts_as_matching_movie():
    boxset = item("collection", "/media/Movies/Movie/file.mkv")
    boxset["Type"] = "BoxSet"
    result = collect(transport({"u1": [boxset], "u2": [boxset]}))
    assert result["status"] == "blocked"
    assert "jellyfin_title_unmatched" in result["blockers"]


def test_unexpected_episode_still_blocks_movie_collection():
    episode = item("episode", "/media/Movies/Movie/file.mkv")
    episode["Type"] = "Episode"
    result = collect(transport({"u1": [episode], "u2": [episode]}))
    assert result["status"] == "blocked"


def test_title_missing_for_one_user_is_unknown_even_after_protected_match():
    result = collect(transport({"u1": [item(tags=["keep-forever"])], "u2": []}))
    assert result["status"] == "blocked"
    assert "jellyfin_title_user_coverage_incomplete" in result["blockers"]
    assert result["signals"] is None
    assert result["identity"] is None


def test_single_backslash_in_path_blocks():
    result = collect(transport({"u1": [item(path="/media/Movies/Movie/a" + chr(92) + "b.mkv")],
                                "u2": [item()]}))
    assert result["status"] == "blocked"
    assert result["signals"] is None
