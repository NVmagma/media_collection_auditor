from copy import deepcopy
from dataclasses import replace
from datetime import datetime

import pytest

from app.sqlite_jellyfin_signal_contract import SIGNAL_FIELDS
from app.sqlite_scheduled_plan import LibraryScan, ScannedTitle, collect_scheduled_plan
from app.sqlite_scheduled_recheck import ProtectionRead, recheck_scheduled_move
from app.sqlite_state import SECTIONS

NOW = datetime(2026, 10, 1)


def setup_plan():
    snapshot = {key: {} for key in SECTIONS}
    snapshot['queued']['Movies/A'] = '2026-01-01'
    plan = collect_scheduled_plan(snapshot=snapshot, revision=3, libraries=['Movies'], now=NOW,
        scan_library=lambda _: LibraryScan(True, [ScannedTitle('Movies/A', 'Holding', 7, {})]),
        timer=lambda: 100)
    return snapshot, plan


def signals(**changes):
    values = {key: False for key in SIGNAL_FIELDS}; values.update(changes)
    return ProtectionRead(True, values)


def recheck(snapshot, plan, **kwargs):
    values = dict(plan=plan, move=plan.moves[0], read_tracking=lambda: (snapshot, 3),
        fetch_protection=lambda move: signals(), clock=lambda: NOW, timer=lambda: 101)
    values.update(kwargs)
    return recheck_scheduled_move(**values)


def test_fresh_request_bracketed_by_current_tracking_reads():
    snapshot, plan = setup_plan(); events = []
    def tracking():
        events.append('tracking'); return snapshot, 3
    def protection(move):
        events.append('fresh_protection'); return signals()
    report = recheck(snapshot, plan, read_tracking=tracking, fetch_protection=protection)
    assert events == ['tracking', 'fresh_protection', 'tracking']
    assert report['status'] == 'revalidated_advisory'
    assert report['production_authorized'] is False
    assert report['filesystem_validation_required'] is True
    assert report['guarded_intent_required'] is True


@pytest.mark.parametrize('flags', [{'protected': True, 'keep_all': True}, {'keep': True}, {'favorite': True}])
def test_title_saved_during_scan_cancels_original_removal_move(flags):
    snapshot, plan = setup_plan()
    report = recheck(snapshot, plan, fetch_protection=lambda move: signals(**flags))
    assert report['reason'] == 'fresh_decision_changed'
    assert report['status'] == 'blocked'


def test_tracking_revision_change_prevents_request():
    snapshot, plan = setup_plan()
    report = recheck(snapshot, plan, read_tracking=lambda: (snapshot, 4),
        fetch_protection=lambda _: pytest.fail('Requested stale plan'))
    assert report['reason'] == 'tracking_not_current'


def test_tracking_revision_change_during_request_blocks():
    snapshot, plan = setup_plan(); revisions = iter([3, 4])
    report = recheck(snapshot, plan, read_tracking=lambda: (snapshot, next(revisions)))
    assert report['status'] == 'blocked'


@pytest.mark.parametrize('mutation', ['pending', 'source_clock', 'other_clock'])
def test_tracking_drift_fails_before_refresh(mutation):
    snapshot, plan = setup_plan()
    if mutation == 'pending': snapshot['sqlite_pending_operations'] = {'op': 'uncertain'}
    if mutation == 'source_clock': snapshot['queued']['Movies/A'] = '2026-09-30'
    if mutation == 'other_clock': snapshot['keep_seen']['Movies/A'] = '2026-01-01'
    result = recheck(snapshot, plan, fetch_protection=lambda _: pytest.fail('Drift refreshed'))
    assert result['reason'] == 'tracking_not_current'


@pytest.mark.parametrize('bad', [ProtectionRead(False, None), ProtectionRead(True, {}),
    ProtectionRead(True, {'protected': 'false'}), signals(protected=True), None])
def test_unavailable_incomplete_or_inconsistent_protection_blocks(bad):
    snapshot, plan = setup_plan()
    assert recheck(snapshot, plan, fetch_protection=lambda _: bad)['status'] == 'blocked'


def test_provider_errors_are_redacted():
    snapshot, plan = setup_plan()
    def fetch(_): raise RuntimeError('token=do-not-print')
    result = recheck(snapshot, plan, fetch_protection=fetch)
    assert result['reason'] == 'fresh_protection_unavailable'
    assert 'do-not-print' not in str(result)


@pytest.mark.parametrize('tick', [99, 3700, float('nan')])
def test_expired_or_invalid_clock_blocks_before_io(tick):
    snapshot, plan = setup_plan()
    report = recheck(snapshot, plan, timer=lambda: tick,
        read_tracking=lambda: pytest.fail('Expired plan read tracking'))
    assert report['status'] == 'blocked'


def test_expiration_during_protection_request_blocks():
    snapshot, plan = setup_plan(); ticks = iter([101, 101, 3700])
    assert recheck(snapshot, plan, timer=lambda: next(ticks))['status'] == 'blocked'


def test_slow_protection_request_blocks():
    snapshot, plan = setup_plan(); ticks = iter([101, 101, 132])
    assert recheck(snapshot, plan, timer=lambda: next(ticks))['reason'] == 'protection_read_deadline_exceeded'


def test_changed_process_cannot_adopt_plan():
    snapshot, plan = setup_plan()
    report = recheck(snapshot, replace(plan, process_id=-1),
        read_tracking=lambda: pytest.fail('Another process adopted plan'))
    assert report['reason'] == 'plan_process_changed'


def test_nonmember_move_is_rejected():
    snapshot, plan = setup_plan()
    report = recheck(snapshot, plan, move=replace(plan.moves[0], media_key='Other'))
    assert report['reason'] == 'move_not_in_plan'


def test_no_tracking_or_plan_mutation():
    snapshot, plan = setup_plan(); before = deepcopy(snapshot)
    recheck(snapshot, plan)
    assert snapshot == before
    assert plan.moves[0].action == 'to_removal'


def test_tracking_delay_after_fresh_read_does_not_leave_protection_unbounded():
    snapshot, plan = setup_plan(); ticks = iter([101, 101, 102, 132])
    report = recheck(snapshot, plan, timer=lambda: next(ticks))
    assert report['reason'] == 'protection_read_deadline_exceeded'


def test_same_revision_unrelated_tracking_mutation_during_request_blocks():
    snapshot, plan = setup_plan()
    def fetch(_):
        snapshot['first_seen']['Other'] = '2026-01-01'
        return signals()
    report = recheck(snapshot, plan, fetch_protection=fetch)
    assert report['reason'] == 'tracking_changed_during_refresh'
