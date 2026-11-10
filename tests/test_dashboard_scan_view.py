"""Keep scan results accurate and leave raw errors and payloads out of the page."""
from copy import deepcopy
import pytest
from app.dashboard_tracking_snapshot import build_scan_view


def record(**updates):
    return {'started_at': '2026-10-27T09:00:00+00:00', 'finished_at': '2026-10-27T09:04:30+00:00',
            'result': 'completed', 'dry_run': True, 'trigger': 'manual', 'result_basis': 'worker_return',
            'moves_proposed': 4, 'discovery_changes': 2, 'moves_completed': 0, 'arr_completed': 0, **updates}


def view(history, **run):
    return build_scan_view({'history_scope': 'current_process', 'running': False, 'queued': False, **run},
                           history, timezone_name='America/Los_Angeles')


def test_preview_counts_completion_duration_and_local_time_are_distinct():
    history = [record()]; before = deepcopy(history)
    result = view(history)
    item = result['latest']
    assert result['current_state'] == 'Waiting'
    assert item['label'] == 'Preview completed' and item['mode'] == 'Preview'
    assert item['moves_proposed'] == 4 and item['moves_completed'] == 0
    assert item['duration_display'] == '4m 30s'
    assert item['duration'] == 270 and item['started'] == '10/27/2026 02:00 America/Los_Angeles'
    assert result['skipped_title_count'] is None and result['blocked_title_count'] is None
    assert history == before and not result['freshness_verified']


def test_raw_errors_unknown_fields_and_unrecognized_reason_never_escape():
    result = view([record(error='secret-token', payload={'path':'/private/media'},
                         result_basis='private-secret', trigger={'secret': True})])
    assert 'secret' not in str(result) and '/private' not in str(result)
    assert result['latest']['trigger'] == 'Not reported'
    assert result['latest']['reason'] == 'No detailed outcome reason was recorded.'


@pytest.mark.parametrize('value', [None, -1, True, 3.5, '0', 100001])
def test_unreported_or_invalid_counts_never_become_zero(value):
    item = view([record(moves_proposed=value, moves_completed=value)])['latest']
    assert item['moves_proposed'] is None and item['moves_completed'] is None


def test_live_is_labeled_only_when_explicitly_recorded_and_mode_missing_is_unknown():
    assert view([record(dry_run=False)])['latest']['mode'] == 'Live (recorded)'
    assert view([record(dry_run=None)])['latest']['mode'] == 'Not reported'
    assert view([record(dry_run='false')])['latest']['mode'] == 'Not reported'


@pytest.mark.parametrize('updates', [{'finished_at': None}, {'finished_at': 'garbage'},
    {'finished_at': '2026-10-27T08:00:00+00:00'}, {'started_at': '2026-10-27T09:00:00'}])
def test_missing_invalid_naive_or_reversed_times_cannot_certify_completion(updates):
    item = view([record(**updates)])['latest']
    assert item['duration'] is None and item['label'] == 'Completion unverified'
    assert item['group'] == 'review'


def test_uncertain_failure_has_no_invented_protection_or_skipped_reason():
    item = view([record(result='failed', result_basis='blocked_or_uncertain',
                        moves_proposed=None, moves_completed=None)])['latest']
    assert item['label'] == 'Blocked / uncertain'
    assert item['moves_completed'] is None
    assert 'do not assume it is safe to replay' in item['reason']
    assert 'protection' not in item['reason']


@pytest.mark.parametrize('run,state', [({'running': True},'Running'), ({'queued': True},'Queued'),
    ({'scheduler_state': 'blocked'},'Blocked'), ({'status': 'unavailable'},'Unavailable')])
def test_current_state_is_not_inferred_from_previous_completion(run, state):
    result = view([record()], **run)
    assert result['current_state'] == state
    assert result['latest']['label'] == 'Preview completed'


def test_empty_unavailable_and_partial_histories_remain_distinct_and_bounded():
    assert view([])['history_available'] and view([])['latest'] is None
    assert not view([], history_scope='unavailable')['history_available']
    assert not view(None)['history_available']
    assert not view([None])['history_available']
    partial = view([record(), None])
    assert partial['history_partial'] and len(partial['rows']) == 1
    assert len(view([record()] * 101)['rows']) == 100


def test_missed_slot_is_not_a_completed_or_skipped_title_scan():
    result = view([], scheduler_state='missed_slot_skipped')
    assert result['current_state'] == 'Slot missed'
    assert result['latest'] is None and result['skipped_title_count'] is None
    assert 'does not represent a completed scan' in result['current_detail']


def test_failed_scan_displays_only_known_failure_stage_labels():
    row=view([record(result='failed',result_basis='blocked_or_uncertain',failure_stage='collection',error='private secret')])['latest']
    assert 'checking folders, clocks, and service data' in row['reason']
    assert 'private secret' not in str(row)
    row=view([record(result='failed',failure_stage='private secret')])['latest']
    assert 'private secret' not in str(row)
