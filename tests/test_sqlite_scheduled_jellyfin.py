from datetime import datetime

import pytest

from app.sqlite_scheduled_jellyfin import scheduled_protection_provider
from app.sqlite_scheduled_plan import PlannedMove

NOW = datetime(2024, 2, 1)
MOVE = PlannedMove('Movies', 'Movie', 'Waiting', 'Holding', 'hold', '2024-01-01', 7)


def item(tags=None):
    return {'Id': 'movie-id', 'Type': 'Movie', 'Path': '/media/Movies/Movie/file.mkv',
            'Tags': tags or [], 'UserData': {'IsFavorite': False, 'Played': False, 'PlayCount': 0}}


def test_each_candidate_requests_new_users_and_pages_without_signal_cache():
    calls = []; tags = []
    def fetch(path, params):
        calls.append(path)
        return [{'Id': 'user'}] if path == '/Users' else {'TotalRecordCount': 1, 'Items': [item(tags)]}
    provider = scheduled_protection_provider(fetch=fetch, bindings={'Movie': ('Movie', 'Movie')}, clock=lambda: NOW)
    assert provider(MOVE).signals['protected'] is False
    tags.append('keep-forever')
    result = provider(MOVE)
    assert result.available and result.signals['protected'] and result.signals['keep_all']
    assert calls == ['/Users', '/Users/user/Items', '/Users', '/Users/user/Items']


def test_user_coverage_failure_never_becomes_clear_protection():
    def fetch(path, params):
        if path == '/Users': return [{'Id': 'one'}, {'Id': 'two'}]
        if '/two/' in path: raise TimeoutError('private transport error')
        return {'TotalRecordCount': 1, 'Items': [item()]}
    provider = scheduled_protection_provider(fetch=fetch, bindings={'Movie': ('Movie', 'Movie')}, clock=lambda: NOW)
    result = provider(MOVE)
    assert result.available is False and result.signals is None


def test_ambiguous_title_is_unavailable():
    def fetch(path, params):
        if path == '/Users': return [{'Id': 'user'}]
        second = item(); second['Id'] = 'other'; second['Path'] = '/else/Movie/file.mkv'
        return {'TotalRecordCount': 2, 'Items': [item(), second]}
    provider = scheduled_protection_provider(fetch=fetch, bindings={'Movie': ('Movie', 'Movie')}, clock=lambda: NOW)
    assert provider(MOVE).available is False


def test_bindings_are_detached_from_caller_changes():
    bindings = {'Movie': ('Movie', 'Movie')}
    provider = scheduled_protection_provider(fetch=lambda p, _: [{'Id': 'user'}] if p == '/Users'
        else {'TotalRecordCount': 1, 'Items': [item()]}, bindings=bindings, clock=lambda: NOW)
    bindings.clear()
    assert provider(MOVE).available


@pytest.mark.parametrize('binding', [('Other', 'Movie'), ('Movie', 'Series'), ('../Movie', 'Movie'), ('Movie', 'BoxSet')])
def test_bad_title_binding_rejected(binding):
    with pytest.raises((ValueError, RuntimeError)):
        scheduled_protection_provider(fetch=lambda *a: None, bindings={'Movie': binding})
