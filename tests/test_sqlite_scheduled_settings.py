"""Effective settings preserve production routing without enabling dispatch."""
from dataclasses import FrozenInstanceError

import pytest

from app.sqlite_scheduled_settings import scheduled_worker_from_settings


def settings(**overrides):
    return {'SQLITE_DAILY_RUN_TIME': '02:00',
            'SQLITE_DAILY_RUN_TIMEZONE': 'America/Los_Angeles', **overrides}


def test_default_movie_and_explicit_tv_preserve_existing_path_vocabulary():
    config = scheduled_worker_from_settings(settings(ENABLE_TV='true'))
    movie, tv = config.libraries
    assert movie.roots == (('Waiting', '/media/Movies'), ('Holding', '/media/Movies_hold'),
                          ('Keep', '/media/Movies_keep'), ('Removal', '/media/Movies_removal'))
    assert tv.roots == (('Waiting', '/media/TV'), ('Holding', '/media/TV_hold'),
                       ('Keep', '/media/TV_keep'), ('Removal', '/media/TV_removal'))
    assert (movie.state_prefix, tv.state_prefix) == ('', 'TV/')
    assert (movie.wait_days, tv.wait_days, tv.holding_days) == (30, 60, 7)
    assert tv.new_content_resets_clock is True
    assert config.maximum_actions == 10


def test_explicit_roots_override_base_and_detach_all_policy():
    values = settings(MEDIA_PATH='/mnt/native', RADARR_TRANSIENT_PATH='/other/waiting',
        RADARR_APP_HOLDING_PATH='/arr-only/holding', MOVIE_WAIT_DAYS='45',
        HOLDING_DAYS='9', MAX_ACTIONS_PER_RUN='3', FAVORITES_TRIGGER_KEEP='false',
        JELLYFIN_API_TOKEN='secret', DRY_RUN='false')
    config = scheduled_worker_from_settings(values)
    values['RADARR_TRANSIENT_PATH'] = '/changed'
    assert dict(config.libraries[0].roots)['Waiting'] == '/other/waiting'
    assert dict(config.libraries[0].roots)['Holding'] == '/mnt/native/Movies_hold'
    assert config.maximum_actions == 3
    assert config.libraries[0].wait_days == 45
    assert config.libraries[0].holding_days == 9
    assert config.favorites_trigger_keep is False
    assert 'secret' not in repr(config) and '/arr-only' not in repr(config)
    with pytest.raises(FrozenInstanceError):
        config.maximum_actions = 4


@pytest.mark.parametrize('key', ['SQLITE_DAILY_RUN_TIME', 'SQLITE_DAILY_RUN_TIMEZONE'])
def test_schedule_never_inferred_from_interval_or_host_timezone(key):
    values = settings(RUN_INTERVAL_HOURS='24', TZ='America/New_York')
    del values[key]
    with pytest.raises(ValueError, match=key):
        scheduled_worker_from_settings(values)


@pytest.mark.parametrize('key', ['ALLOW_PERMANENT_DELETE', 'ALLOW_FILESYSTEM_DELETE',
    'ALLOW_CROSS_FILESYSTEM_MOVES', 'ENABLE_SEASON_PRUNING'])
def test_unsupported_destructive_policy_is_rejected(key):
    with pytest.raises(ValueError, match=key):
        scheduled_worker_from_settings(settings(**{key: 'true'}))


@pytest.mark.parametrize('overrides', [
    {'MAX_ACTIONS_PER_RUN': '0'}, {'HOLDING_DAYS': '0'}, {'MOVIE_WAIT_DAYS': '-1'},
    {'MAX_ACTIONS_PER_RUN': '100001'}, {'MAX_ACTIONS_PER_RUN': '1.0'},
    {'DRY_RUN': 'maybe'}, {'ENABLE_TV': True}, {'MEDIA_PATH': 'relative'},
    {'SQLITE_DAILY_RUN_TIME': '25:00'}, {'SQLITE_DAILY_RUN_TIMEZONE': 'unknown/zone'},
    {'ENABLE_MOVIES': 'false', 'ENABLE_TV': 'false'},
    {'RADARR_KEEP_PATH': '/media/Movies'},
    {'ENABLE_TV': 'true', 'SONARR_KEEP_PATH': '/media/Movies_keep'},
])
def test_bad_effective_settings_never_produce_a_policy(overrides):
    with pytest.raises(ValueError):
        scheduled_worker_from_settings(settings(**overrides))


def test_tv_only_uses_tv_prefix_and_disabled_library_does_not_leak():
    config = scheduled_worker_from_settings(settings(ENABLE_MOVIES='false', ENABLE_TV='true',
        TV_NEW_EPISODES_RESET_CLOCK='false', TV_WAIT_DAYS='70'))
    assert len(config.libraries) == 1
    assert config.libraries[0].media_key('Same title') == 'TV/Same title'
    assert config.libraries[0].wait_days == 70
    assert config.libraries[0].new_content_resets_clock is False


def test_saved_schedule_round_trip_and_validation(tmp_path, monkeypatch):
    from app import config_store
    monkeypatch.setattr(config_store, 'CONFIG_FILE', tmp_path / 'settings.json')
    values = settings()
    config_store.save_config({k: config_store.validate(k, v) for k, v in values.items()})
    config = scheduled_worker_from_settings(config_store.load_config())
    assert config.schedule.local_time == '02:00'
    assert config.schedule.timezone_name == 'America/Los_Angeles'
    for key, value in [('SQLITE_DAILY_RUN_TIME', '2am'),
                       ('SQLITE_DAILY_RUN_TIMEZONE', 'not/a-zone')]:
        with pytest.raises(ValueError):
            config_store.validate(key, value)
    assert config_store.validate('SQLITE_DAILY_RUN_TIME', '') == ''
    assert config_store.validate('SQLITE_DAILY_RUN_TIMEZONE', '') == ''


def test_effective_settings_match_existing_production_library_builder(monkeypatch):
    import importlib
    from pathlib import Path
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'app'))
    values = settings(ENABLE_MOVIES='true', ENABLE_TV='true', MEDIA_PATH='/native/media',
        RADARR_TRANSIENT_PATH='/custom/movies', SONARR_KEEP_PATH='/custom/tv-keep',
        MOVIE_WAIT_DAYS='40', TV_WAIT_DAYS='80', HOLDING_DAYS='8',
        TV_NEW_EPISODES_RESET_CLOCK='false')
    for prefix in ('RADARR', 'SONARR'):
        for stage in ('TRANSIENT', 'HOLDING', 'KEEP', 'REMOVAL'):
            monkeypatch.delenv(f'{prefix}_{stage}_PATH', raising=False)
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    import collection_auditor
    auditor = importlib.reload(collection_auditor)
    actual = auditor.build_libraries()
    policy = scheduled_worker_from_settings(values)
    for original, captured in zip(actual, policy.libraries, strict=True):
        assert captured.name == original['name']
        assert captured.state_prefix == original['state_prefix']
        assert captured.jellyfin_type == original['jellyfin_type']
        assert captured.wait_days == original['wait_days']
        assert captured.new_content_resets_clock == original['new_content_resets_clock']
        assert captured.roots == tuple((stage, original[key]) for stage, key in
            [('Waiting', 'transient'), ('Holding', 'holding'), ('Keep', 'keep'), ('Removal', 'removal')])


def test_settings_policy_drives_actual_daily_movie_tv_dispatch():
    import sys
    if sys.platform != 'linux':
        pytest.skip('Actual no-replace rename requires Linux')
    from scripts.sqlite_scheduled_routed_slot_fixture import ScheduledRoutedSlotFixtureTests
    fixture = ScheduledRoutedSlotFixtureTests()
    try:
        fixture.setUp()
        values = settings(ENABLE_TV='true', HOLDING_DAYS=str(fixture.config.libraries[0].holding_days),
            MAX_ACTIONS_PER_RUN='1',
            SQLITE_DAILY_RUN_TIME=fixture.config.schedule.local_time,
            SQLITE_DAILY_RUN_TIMEZONE=fixture.config.schedule.timezone_name)
        for library, prefix in zip(fixture.config.libraries, ('RADARR', 'SONARR'), strict=True):
            for stage, path in library.roots:
                field = 'TRANSIENT' if stage == 'Waiting' else stage.upper()
                values[f'{prefix}_{field}_PATH'] = path
            values['MOVIE_WAIT_DAYS' if prefix == 'RADARR' else 'TV_WAIT_DAYS'] = str(library.wait_days)
        values['TV_NEW_EPISODES_RESET_CLOCK'] = str(fixture.config.libraries[1].new_content_resets_clock).lower()
        policy = scheduled_worker_from_settings(values)
        result = fixture.execute(config=policy)
        assert result['status'] == 'disposable_scheduled_routed_slot_complete'
        assert len(result['completed']) == 1
        assert fixture.events == ['scan:Movies', 'scan:TV', 'move:Movies']
        assert fixture.fixture.path(0, 'holding').is_dir()
        assert fixture.fixture.path(1, 'transient').is_dir()
    finally:
        fixture.doCleanups()
