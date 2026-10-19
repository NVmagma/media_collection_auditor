"""Cross-container path mappings are advisory and never authorize recovery."""

import pytest

from app.sqlite_recovery_mount_binding import inspect_mount_namespace_binding


ROOTS = {"local": "/media", "jellyfin": "/jf", "arr": "/arr"}
DEST = "/media/Shows_keep/A"
JF = "/jf/Shows_keep/A"
ARR = "/arr/Shows_keep/A"


def inspect(**overrides):
    options = dict(
        local_destination=DEST, jellyfin_path=JF, arr_path=ARR,
        media_type="Series", roots=ROOTS,
    )
    options.update(overrides)
    return inspect_mount_namespace_binding(**options)


def test_distinct_namespaces_can_be_consistent_but_not_authorized():
    result = inspect()
    assert result["mount_binding"] == "relative_paths_consistent_unverified"
    assert result["authorization"] == "not_authorized"
    assert result["status"] == "blocked"
    assert "/media" not in str(result)


def test_movie_file_parent_under_distinct_namespace():
    result = inspect(media_type="Movie", jellyfin_path=JF + "/Film.mkv")
    assert result["mount_binding"] == "relative_paths_consistent_unverified"
    assert result["authorization"] == "not_authorized"


@pytest.mark.parametrize("changes,reason", [
    ({"roots": None}, "mount_roots_unavailable"),
    ({"roots": {"local": "/media", "arr": "/arr"}}, "mount_roots_unavailable"),
    ({"roots": {**ROOTS, "other": "/elsewhere"}}, "mount_roots_unavailable"),
    ({"roots": {**ROOTS, "arr": "relative"}}, "invalid_mount_roots"),
    ({"roots": {**ROOTS, "arr": "/arr/../arr"}}, "invalid_mount_roots"),
    ({"local_destination": "/media/../media/Shows_keep/A"}, "invalid_observed_paths"),
    ({"jellyfin_path": "/jf/Shows_keep/A/../B"}, "invalid_observed_paths"),
    ({"arr_path": "/arr/Shows_keep/AB"}, "relative_paths_disagree"),
    ({"arr_path": "/arr/Shows_keep/A/subdir"}, "relative_paths_disagree"),
    ({"arr_path": "/arr2/Shows_keep/A"}, "path_outside_declared_mount"),
    ({"jellyfin_path": "/jf"}, "mount_root_not_title"),
    ({"media_type": "Episode"}, "invalid_media_type"),
    ({"local_destination": "/media"}, "mount_root_not_title"),
])
def test_ambiguous_mapping_fails_closed(changes, reason):
    result = inspect(**changes)
    assert result["reason"] == reason
    assert result["mount_binding"] == "unverified"
    assert result["authorization"] == "not_authorized"
    assert "/Shows_keep" not in str(result)


def test_movie_nested_file_does_not_match_title():
    result = inspect(media_type="Movie", jellyfin_path=JF + "/extras/Film.mkv")
    assert result["reason"] == "relative_paths_disagree"


def test_root_slash_is_supported_without_prefix_collision():
    result = inspect(
        roots={"local": "/", "jellyfin": "/", "arr": "/"},
        local_destination="/title", jellyfin_path="/title", arr_path="/title",
    )
    assert result["mount_binding"] == "relative_paths_consistent_unverified"
