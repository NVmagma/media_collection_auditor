import json
from datetime import datetime

import pytest

from app.media_libraries import (
    MediaLibrary,
    configured_media_libraries,
    legacy_media_libraries,
    parse_media_libraries,
)
from app.json_lifecycle_plan import LibraryObservation, TitleObservation, plan_scan


def encoded(*items):
    return json.dumps(items)


def test_legacy_settings_preserve_existing_movie_and_tv_defaults():
    assert legacy_media_libraries({"ENABLE_MOVIES": "true", "ENABLE_TV": "true"}) == (
        MediaLibrary("Movies", "movie", "/media/Movies"),
        MediaLibrary("TV", "tv", "/media/TV"),
    )


def test_empty_saved_registry_uses_legacy_settings():
    assert configured_media_libraries({
        "MEDIA_LIBRARIES": "",
        "ENABLE_MOVIES": "true",
        "ENABLE_TV": "false",
    }) == (MediaLibrary("Movies", "movie", "/media/Movies"),)


def test_saved_registry_supports_multiple_typed_libraries():
    result = parse_media_libraries(
        encoded(
            {"name": "Films", "type": "movie", "root": "/media/films"},
            {"name": "Documentaries", "type": "movie", "root": "/media/documentaries"},
            {"name": "Series", "type": "tv", "root": "/media/series"},
        )
    )
    assert result[1].name == "Documentaries"
    assert result[2].is_tv


@pytest.mark.parametrize(
    "raw",
    [
        "[]",
        encoded({"name": "Movies", "type": "music", "root": "/media/music"}),
        encoded({"name": "Movies", "type": "movie", "root": "relative"}),
        encoded({"name": "Movies", "type": "movie", "root": "/"}),
        encoded(
            {"name": "Movies", "type": "movie", "root": "/media/movies"},
            {"name": "movies", "type": "tv", "root": "/media/tv"},
        ),
        '{"name":"Movies","type":"movie","root":"/media/movies"}',
        '[{"name":"Movies","type":"movie","root":"/media"},{"name":"TV","type":"tv","root":"/media/tv"}]',
    ],
)
def test_invalid_saved_registry_fails_closed(raw):
    with pytest.raises(ValueError):
        parse_media_libraries(raw)


def test_duplicate_json_keys_are_rejected():
    with pytest.raises(ValueError, match="valid JSON"):
        parse_media_libraries(
            '[{"name":"Movies","type":"movie","root":"/media/movies",'
            '"root":"/media/other"}]'
        )


def test_custom_library_uses_a_namespaced_lifecycle_key():
    snapshot = {
        "first_seen": {"Documentaries/Film": "2026-01-01T00:00:00"},
        "queued": {},
        "in_removal": {},
        "keep_seen": {},
        "arr_sync_pending": {},
        "unknown": {},
    }
    result = plan_scan(
        snapshot=snapshot,
        libraries=[LibraryObservation(
            "Documentaries", True, True,
            (TitleObservation(
                "Documentaries/Film", "Waiting", 1,
                {"played": True, "favorite": False, "disliked": True,
                 "keep": False, "keep_all": False, "protected": False},
                "exact_source_match"
            ),),
            "movie",
        )],
        now=datetime(2026, 1, 10),
        per_library_action_limit=5,
    )
    assert result["moves"][0].media_key == "Documentaries/Film"
