from datetime import datetime
import pytest
from app.sqlite_scheduled_jellyfin import (_ScanCatalog, scheduled_inventory_signal_reader,
                                          scheduled_protection_provider)
from app.sqlite_scheduled_worker import ScheduledTitleBinding
from app.sqlite_scheduled_plan import PlannedMove

NOW = datetime(2026, 10, 30)


def test_six_user_catalog_is_shared_across_600_titles_but_not_fresh_move_checks():
    calls = []
    tags = []
    def fetch(path, params):
        calls.append((path, params))
        if path == '/Users':
            return [{'Id': 'user' + str(i)} for i in range(6)]
        start, limit = params['StartIndex'], params['Limit']
        return {'TotalRecordCount': 600, 'Items': [
            {'Id': str(i), 'Type': 'Movie', 'Path': f'/movies/Movie {i}/file.mkv',
             'Tags': list(tags), 'UserData': {'Played': False, 'PlayCount': 0, 'IsFavorite': False}}
            for i in range(start, min(start + limit, 600))]}
    reader = scheduled_inventory_signal_reader(fetch=fetch, clock=lambda: NOW, share_catalog=True)
    reader.begin_scan()
    for i in range(600):
        assert reader(ScheduledTitleBinding('Movies', f'Movie {i}', f'Movie {i}', 'Waiting', 'Movie'))['protected'] is False
    assert len(calls) == 37  # One users request + six pages for each of six users.
    tags.append('keep-forever')
    move = PlannedMove('Movies', 'Movie 0', 'Waiting', 'Holding', 'hold', '2024-01-01', 7)
    protect = scheduled_protection_provider(fetch=fetch, bindings={'Movie 0': ('Movie 0', 'Movie')}, clock=lambda: NOW)
    assert protect(move).signals['protected'] is True
    assert len(calls) == 74
    # A post-checkpoint rebuild must observe the changed catalog.
    reader.begin_scan()
    assert reader(ScheduledTitleBinding('Movies', 'Movie 0', 'Movie 0', 'Waiting', 'Movie'))['protected'] is True
    assert len(calls) == 111


def test_catalog_detaches_values_and_keys_queries_separately():
    source = {'Items': []}
    calls = []
    catalog = _ScanCatalog(lambda path, params: calls.append((path, params)) or source)
    catalog('/x', {'kind': 'Movie'})['Items'].append('mutation')
    assert catalog('/x', {'kind': 'Movie'}) == {'Items': []}
    catalog('/x', {'kind': 'Series'})
    assert len(calls) == 2


def test_catalog_failure_poisoned_until_new_pass_and_does_not_retry():
    calls = []
    def fail(path, params):
        calls.append(path)
        raise TimeoutError('private transport text')
    catalog = _ScanCatalog(fail)
    with pytest.raises(TimeoutError): catalog('/x', None)
    with pytest.raises(RuntimeError, match='Scan catalog unavailable'): catalog('/y', None)
    assert calls == ['/x']
    catalog.reset()
    with pytest.raises(TimeoutError): catalog('/x', None)
    assert len(calls) == 2


def test_catalog_byte_limit_fails_closed():
    catalog = _ScanCatalog(lambda *args: {'Items': ['x' * 100]}, maximum_bytes=10)
    with pytest.raises(RuntimeError, match='limit'): catalog('/x', None)
    assert catalog.pages == {}
    with pytest.raises(RuntimeError, match='unavailable'): catalog('/x', None)
