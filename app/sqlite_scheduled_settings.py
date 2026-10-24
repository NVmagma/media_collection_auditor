"""Detach scheduled policy from effective application settings without side effects.

The caller supplies settings after saved-config/environment precedence is resolved.
No settings are loaded, clients initialized, paths opened or backend activated here.
JSON retains its interval/manual behavior; SQLite schedule fields are preparatory.
"""
from collections.abc import Mapping
import posixpath

from app.sqlite_scheduled_worker import configured_scheduled_worker


def scheduled_worker_from_settings(settings):
    """Resolve the existing movie/TV path vocabulary into immutable run policy.

    A daily time and IANA zone must both be explicit. Unsupported destructive
    policy is rejected rather than silently omitted by the whole-title runner.
    Credentials and Arr clients are never retained in the returned policy.
    """
    if not isinstance(settings, Mapping):
        raise ValueError('Effective application settings mapping required')
    values = dict(settings)

    def text(key, default=None):
        value = values.get(key, default)
        if not isinstance(value, str):
            raise ValueError(f'{key}: string setting required')
        return value.strip()

    def flag(key, default):
        value = text(key, default).lower()
        if value not in ('true', 'false'):
            raise ValueError(f'{key}: true or false required')
        return value == 'true'

    def number(key, default, minimum=0):
        value = text(key, default)
        if not value.isascii() or not value.isdecimal():
            raise ValueError(f'{key}: bounded whole number required')
        result = int(value)
        if not minimum <= result <= 100000:
            raise ValueError(f'{key}: bounded whole number required')
        return result

    for key in ('ALLOW_PERMANENT_DELETE', 'ALLOW_FILESYSTEM_DELETE',
                'ALLOW_CROSS_FILESYSTEM_MOVES', 'ENABLE_SEASON_PRUNING'):
        if flag(key, 'false'):
            raise ValueError(f'{key}: unsupported scheduled policy')
    # Validate dry-run explicitly, but it never grants dispatch permission here.
    flag('DRY_RUN', 'true')
    base = text('MEDIA_PATH', '/media')
    libraries = []
    for enabled, name, kind, prefix, folder, wait in (
            ('ENABLE_MOVIES', 'Movies', 'Movie', 'RADARR', 'Movies', '30'),
            ('ENABLE_TV', 'TV', 'Series', 'SONARR', 'TV', '60')):
        if not flag(enabled, 'true' if kind == 'Movie' else 'false'):
            continue
        roots = {}
        for stage, suffix in (('transient', ''), ('holding', '_hold'),
                              ('keep', '_keep'), ('removal', '_removal')):
            explicit = text(f'{prefix}_{stage.upper()}_PATH', '')
            roots[stage] = explicit or posixpath.join(base, folder + suffix)
        libraries.append(dict(name=name, jellyfin_type=kind,
            state_prefix='' if kind == 'Movie' else 'TV/', **roots,
            wait_days=number('MOVIE_WAIT_DAYS' if kind == 'Movie' else 'TV_WAIT_DAYS', wait),
            new_content_resets_clock=(flag('TV_NEW_EPISODES_RESET_CLOCK', 'true')
                                      if kind == 'Series' else False)))
    return configured_scheduled_worker(libraries=libraries,
        local_time=text('SQLITE_DAILY_RUN_TIME'),
        timezone_name=text('SQLITE_DAILY_RUN_TIMEZONE'),
        holding_days=number('HOLDING_DAYS', '7', minimum=1),
        maximum_actions=number('MAX_ACTIONS_PER_RUN', '10', minimum=1),
        favorites_trigger_keep=flag('FAVORITES_TRIGGER_KEEP', 'true'))
