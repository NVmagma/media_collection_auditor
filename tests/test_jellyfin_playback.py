import pytest

from app import jellyfin_playback


@pytest.mark.parametrize(('item', 'paused', 'season', 'reason'), [
    (None, False, None, None),
    ({'Path': '/jellyfin/Shows/Show/Season 1/episode.mkv'}, True, None, 'active_playback'),
    ({'Path': '/jellyfin/Shows/Show/Season 1/episode.mkv', 'ParentIndexNumber': 1},
     False, 1, 'active_playback'),
    ({'Path': '/jellyfin/Shows/Show/Season 2/episode.mkv', 'ParentIndexNumber': 2},
     False, 1, None),
    ({'Path': '/jellyfin/Shows/Show 2/Season 1/episode.mkv'}, False, None, None),
    ({'Path': '/jellyfin/Shows/Show/Season 1/episode.mkv'}, False, 1, 'playback_unavailable'),
    ({'Type': 'Episode'}, False, None, 'playback_unavailable'),
])
def test_playback_scope(monkeypatch, item, paused, season, reason):
    def get(path, params):
        assert (path, params) == ('/Sessions', None)
        return [{'Id': 'session', 'NowPlayingItem': item, 'PlayState': {'IsPaused': paused}}]

    monkeypatch.setattr(jellyfin_playback, 'ScheduledJellyfinGET', lambda **kwargs: get)
    source = '/media/TV/Show' + ('/Season 1' if season else '')
    if reason:
        with pytest.raises(jellyfin_playback.PlaybackDeferred, match=reason):
            jellyfin_playback.check_active_playback({}, 'Show', source, season)
    else:
        jellyfin_playback.check_active_playback({}, 'Show', source, season)


def test_unavailable_sessions_defer_without_leaking_error(monkeypatch):
    def get(path, params):
        raise jellyfin_playback.ScheduledTransportError('private session error')

    monkeypatch.setattr(jellyfin_playback, 'ScheduledJellyfinGET', lambda **kwargs: get)
    with pytest.raises(jellyfin_playback.PlaybackDeferred, match='^playback_unavailable$'):
        jellyfin_playback.check_active_playback({}, 'Movie', '/media/Movies/Movie')
