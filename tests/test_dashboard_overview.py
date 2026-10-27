"""Overview is a bounded projection of the captured inventory, never a collector."""
from copy import deepcopy
from datetime import datetime
import pytest
from app.dashboard_tracking_snapshot import dashboard_overview, lifecycle_clock, summarize_dashboard_clocks


def fixture():
    stages = {name: [] for name in ('Waiting', 'Holding', 'Removal', 'Keep')}
    for stage, library, title, since in (
        ('Waiting', 'Movies', 'Newest', '2026-10-20T11:30:00'),
        ('Waiting', 'TV', 'Oldest', '2026-08-01T11:30:00'),
        ('Waiting', 'Movies', 'Missing clock', None),
        ('Waiting', 'Movies', 'Invalid clock', 'broken'),
        ('Holding', 'TV', 'Sooner', '2026-10-01T11:30:00'),
        ('Holding', 'Movies', 'Later', '2026-10-10T11:30:00'),
        ('Holding', 'TV', 'Future clock', '2099-01-01T00:00:00')):
        item = {'title': title, 'library': library, 'since': since, 'private_extension': 'never-project'}
        item.update(lifecycle_clock(since, limit=7, now=datetime(2026, 10, 27, 12)))
        stages[stage].append(item)
    coverage = summarize_dashboard_clocks({}, stages, [], libraries=['Movies', 'TV'])
    return stages, coverage


def test_lists_order_known_dates_cap_across_libraries_and_keep_inputs_unchanged():
    stages, coverage = fixture(); before = deepcopy((stages, coverage))
    report = dashboard_overview(stages, coverage, libraries=['Movies', 'TV'], limit=2)
    lists = report['lists']
    assert [row['title'] for row in lists['oldest_waiting']['items']] == ['Oldest', 'Newest']
    assert [row['title'] for row in lists['leaving_soon']['items']] == ['Sooner', 'Later']
    assert lists['oldest_waiting']['more'] == 2
    assert lists['oldest_waiting']['unusable_dates'] == 2
    assert lists['leaving_soon']['unusable_dates'] == 1
    assert 'private_extension' not in str(report) and 'never-project' not in str(report)
    assert not report['freshness_verified']
    assert (stages, coverage) == before


def test_unknown_dates_follow_known_dates_and_do_not_acquire_estimates():
    stages, coverage = fixture()
    lists = dashboard_overview(stages, coverage, libraries=['Movies', 'TV'])['lists']
    assert lists['leaving_soon']['items'][-1]['title'] == 'Future clock'
    assert lists['leaving_soon']['items'][-1]['next_review_display'] is None
    assert {item['since_display'] for item in lists['oldest_waiting']['items'][-2:]} == {
        'Invalid saved date', 'Not yet tracked'}


def test_disabled_libraries_are_excluded_before_limit_and_ties_are_stable():
    stages, coverage = fixture()
    one = dashboard_overview(stages, coverage, libraries=['Movies'], limit=1)
    assert one['lists']['leaving_soon']['observed_folders'] == 1
    assert one['lists']['leaving_soon']['items'][0]['title'] == 'Later'
    first = stages['Waiting'][0]
    stages['Waiting'].append({**first, 'title': 'Alpha'})
    result = dashboard_overview(stages, coverage, libraries=['Movies'], limit=1)
    assert result['lists']['oldest_waiting']['items'][0]['title'] == 'Alpha'


def test_missing_tracking_is_unavailable_instead_of_empty_or_stale():
    stages, coverage = fixture()
    coverage['complete'] = False
    result = dashboard_overview(stages, coverage, libraries=['Movies', 'TV'], tracking_available=False)
    assert all(row['items'] is None and row['status'] == 'unavailable' for row in result['lists'].values())
    assert result['attention'][0]['title'] == 'Tracking unavailable'


def test_partial_empty_inventory_cannot_claim_an_empty_collection():
    stages, coverage = fixture()
    coverage['complete'] = False
    coverage['rows'][1]['status'] = 'directory_unavailable'  # Movies Holding
    stages['Holding'] = []
    result = dashboard_overview(stages, coverage, libraries=['Movies', 'TV'])
    assert result['lists']['leaving_soon']['items'] == []
    assert result['lists']['leaving_soon']['status'] == 'partial'
    assert any(row['title'] == 'Coverage is incomplete' for row in result['attention'])
    assert any(row['title'].startswith('At least ') for row in result['attention'])


def test_known_empty_lists_remain_distinct_from_unavailable():
    stages = {stage: [] for stage in ('Waiting', 'Holding', 'Keep', 'Removal')}
    coverage = summarize_dashboard_clocks({}, stages, [], libraries=['Movies'])
    result = dashboard_overview(stages, coverage, libraries=['Movies'])
    assert all(row['status'] == 'observed' and row['items'] == [] for row in result['lists'].values())
    assert result['attention'] == []


@pytest.mark.parametrize('limit', [True, 0, 11, None])
def test_invalid_limit_is_rejected(limit):
    stages, coverage = fixture()
    with pytest.raises(ValueError):
        dashboard_overview(stages, coverage, libraries=['Movies'], limit=limit)
