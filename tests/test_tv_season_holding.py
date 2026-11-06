from datetime import datetime, timezone

from app.tv_season_holding import holding_seasons
from app.tv_season_move import ARCHIVE


def test_staged_dates_use_current_grace_period_without_exposing_paths():
    now = datetime(2026, 11, 9, tzinfo=timezone.utc)
    state = {ARCHIVE: {'TV/Example/1': {'name': 'Season 01', 'staged_at': '2026-11-01T00:00:00+00:00',
                                       'active_parent': '/private/show'},
                       'TV/Example/2': {'name': 'Season 2', 'staged_at': '2026-11-08T00:00:00+00:00'}}}
    view = holding_seasons(state, holding_days=7, display_zone='America/Los_Angeles', now=now)
    assert not view['incomplete']
    assert [row['grace_ended'] for row in view['rows']] == [True, False]
    assert view['rows'][0]['grace_ends_display'] == '11/07/2026 16:00 America/Los_Angeles'
    assert '/private' not in str(view)
    assert state[ARCHIVE]['TV/Example/1']['active_parent'] == '/private/show'
    assert holding_seasons(state, holding_days=None, now=now)['rows'][0]['grace_ends_display'] is None


def test_invalid_special_and_future_records_do_not_get_deadlines():
    now = datetime(2026, 11, 9, tzinfo=timezone.utc)
    state = {ARCHIVE: {'TV/Example/0': {'name': 'Season 0', 'staged_at': '2026-11-01T00:00:00+00:00'},
                       'TV/Example/2': {'name': 'Season 2', 'staged_at': '2026-12-01T00:00:00+00:00'}}}
    assert holding_seasons(state, holding_days=7, now=now) == {'rows': [], 'incomplete': True}
