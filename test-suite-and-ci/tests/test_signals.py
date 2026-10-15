"""Reading favorites and tags from Jellyfin (with a fake Jellyfin), including the protect tag."""


def fake_jellyfin(items_by_type):
    def fake_get(path, params=None):
        if path == "/Users":
            return [{"Id": "alice"}, {"Id": "bob"}]
        kind = params["IncludeItemTypes"]
        user = path.split("/")[2]
        return {"Items": items_by_type[kind].get(user, [])}
    return fake_get


def movie(path, favorite=False, played=False, tags=()):
    return {"Path": path, "Tags": list(tags), "UserData": {"IsFavorite": favorite, "Played": played, "PlayCount": 0}}


def real_module(make_auditor, **env):
    """The script with its real get_signals, whose Jellyfin calls the test can replace."""
    import importlib
    make_auditor(**env)
    import collection_auditor
    return importlib.reload(collection_auditor)


def test_favorite_by_any_user_counts(make_auditor):
    ca = real_module(make_auditor)
    path = "/data/Movies/Pretty Woman (1990)/Pretty Woman (1990).mkv"
    ca.jellyfin_get = fake_jellyfin({"Movie": {
        "alice": [movie(path)],
        "bob": [movie(path, favorite=True, played=True)],
    }})
    signals = ca.get_signals("Movie")

    assert signals["Pretty Woman (1990)"]["favorite"] is True
    assert signals["Pretty Woman (1990)"]["played"] is True


def test_tags_are_read_case_insensitively(make_auditor):
    ca = real_module(make_auditor)
    ca.jellyfin_get = fake_jellyfin({"Movie": {"alice": [
        movie("/m/Hated (2001)/Hated (2001).mkv", tags=["Not-At-All"]),
    ]}})
    signals = ca.get_signals("Movie")

    assert signals["Hated (2001)"]["disliked"] is True
    assert signals["Hated (2001)"]["favorite"] is False


def test_protect_tag_acts_as_favorite_and_blocks_pruning(make_auditor):
    ca = real_module(make_auditor)
    ca.jellyfin_get = fake_jellyfin({"Movie": {"alice": [
        movie("/m/Protected (2005)/Protected (2005).mkv", tags=["keep-forever"]),
        movie("/m/Plain (2006)/Plain (2006).mkv"),
    ]}})
    signals = ca.get_signals("Movie")

    assert signals["Protected (2005)"]["protected"] is True
    assert signals["Protected (2005)"]["favorite"] is True       # so it is kept / rescued like a favorite
    assert signals["Protected (2005)"]["keep_all"] is True       # and never season-pruned
    assert signals["Plain (2006)"]["protected"] is False
    assert signals["Plain (2006)"]["favorite"] is False


def test_custom_tag_names(make_auditor):
    ca = real_module(make_auditor, PROTECT_TAG="forever", DISLIKE_TAG="yuck")
    ca.jellyfin_get = fake_jellyfin({"Movie": {"alice": [
        movie("/m/A (2000)/A (2000).mkv", tags=["forever"]),
        movie("/m/B (2000)/B (2000).mkv", tags=["yuck"]),
        movie("/m/C (2000)/C (2000).mkv", tags=["keep-forever", "not-at-all"]),   # default names: ignored
    ]}})
    signals = ca.get_signals("Movie")

    assert signals["A (2000)"]["protected"] is True
    assert signals["B (2000)"]["disliked"] is True
    assert signals["C (2000)"]["protected"] is False and signals["C (2000)"]["disliked"] is False


def test_series_are_matched_by_show_folder(make_auditor):
    ca = real_module(make_auditor)
    ca.jellyfin_get = fake_jellyfin({"Series": {"alice": [
        {"Path": "/tv/FROM (2022)", "Tags": ["keep-all-seasons"], "UserData": {"IsFavorite": True}},
    ]}})
    signals = ca.get_signals("Series")

    assert signals["FROM (2022)"]["favorite"] is True
    assert signals["FROM (2022)"]["keep_all"] is True


def test_protected_movie_is_kept_even_without_a_family_favorite(make_auditor):
    a = make_auditor()
    a.add("Movies", "Protected (2005)")
    a.movie("Protected (2005)", protected=True, favorite=True, keep_all=True)
    a.run()

    assert a.where("Protected (2005)") == "Movies_keep"
