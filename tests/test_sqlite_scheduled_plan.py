from datetime import datetime
from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

import app.sqlite_scheduled_plan as module
from app.sqlite_scheduled_plan import LibraryScan, ScannedTitle, ScheduledScanBlocked, collect_scheduled_plan
from app.sqlite_state import SECTIONS

NOW = datetime(2026, 10, 1)


def state():
    result = {key: {} for key in SECTIONS}
    result['first_seen'] = {'Movies/A': '2026-01-01', 'TV/B': '2026-01-01'}
    return result


def title(key='Movies/A', stage='Waiting', signals=None):
    return ScannedTitle(key, stage, 7, {} if signals is None else signals)


def plan(collector, **kwargs):
    values = dict(snapshot=state(), revision=5, libraries=['Movies', 'TV'],
                  scan_library=collector, now=NOW)
    values.update(kwargs)
    return collect_scheduled_plan(**values)


def test_all_library_iterators_finish_before_any_decision(monkeypatch):
    events = []
    real = module.review_decision
    def decision(*args, **kwargs):
        events.append('decision')
        return real(*args, **kwargs)
    monkeypatch.setattr(module, 'review_decision', decision)
    def scan(library):
        def rows():
            events.append(library + ':begin')
            yield title('Movies/A' if library == 'Movies' else 'TV/B')
            events.append(library + ':end')
        return LibraryScan(True, rows())
    result = plan(scan)
    assert events == ['Movies:begin', 'Movies:end', 'TV:begin', 'TV:end', 'decision', 'decision']
    assert len(result.moves) == 2
    assert result.authorization == 'not_authorized'


@pytest.mark.parametrize('failure', ['incomplete', 'exception', 'late_iterator_exception'])
def test_later_library_failure_exposes_no_partial_plan_or_decisions(monkeypatch, failure):
    def forbidden(*args, **kwargs):
        pytest.fail('Decision reached before complete scan')
    monkeypatch.setattr(module, 'review_decision', forbidden)
    def scan(library):
        if library == 'Movies':
            return LibraryScan(True, [title()])
        if failure == 'incomplete':
            return LibraryScan(False, [])
        if failure == 'exception':
            raise RuntimeError('transport failed')
        def rows():
            yield title('TV/B')
            raise RuntimeError('pagination failed')
        return LibraryScan(True, rows())
    with pytest.raises((RuntimeError, ScheduledScanBlocked)):
        plan(scan)


def test_snapshot_and_signals_detached_and_plan_immutable():
    original = state(); before = deepcopy(original); signals = {}
    def scan(library):
        if library == 'Movies':
            return LibraryScan(True, [title(signals=signals)])
        signals['keep'] = True
        original['first_seen'].clear()
        return LibraryScan(True, [])
    result = plan(scan, snapshot=original)
    assert result.moves[0].action == 'hold'
    with pytest.raises(FrozenInstanceError):
        result.revision = 6
    assert before['first_seen']['Movies/A'] == result.moves[0].source_clock


def test_action_cap_does_not_truncate_collection():
    visited = []
    def scan(library):
        visited.append(library)
        return LibraryScan(True, [title('Movies/A' if library == 'Movies' else 'TV/B')])
    result = plan(scan, maximum_actions=1)
    assert visited == ['Movies', 'TV']
    assert result.scanned_titles == 2 and result.capped_moves == 1
    assert len(result.moves) == 1


def test_unavailable_protection_and_removal_never_produce_moves():
    snapshot = state(); snapshot['first_seen'].pop('TV/B'); snapshot['in_removal']['TV/B'] = '2026-01-01'
    result = plan(lambda lib: LibraryScan(True, [ScannedTitle('Movies/A', 'Waiting', 7, None)]
        if lib == 'Movies' else [title('TV/B', 'Removal')]), snapshot=snapshot)
    assert result.moves == ()
    assert len(result.skipped) == 2


def test_pending_operation_blocks_before_collector():
    snapshot = state(); snapshot['sqlite_pending_operations'] = {'op': 'uncertain'}
    with pytest.raises(ScheduledScanBlocked, match='unresolved'):
        plan(lambda lib: pytest.fail('Collector called with pending operation'), snapshot=snapshot)


def test_duplicate_keys_across_libraries_block_entire_plan():
    with pytest.raises(ScheduledScanBlocked, match='duplicate'):
        plan(lambda lib: LibraryScan(True, [title()]))


def test_title_limit_blocks_instead_of_making_partial_plan():
    with pytest.raises(ScheduledScanBlocked, match='title_limit'):
        plan(lambda lib: LibraryScan(True, [title('Movies/A' if lib == 'Movies' else 'TV/B')]), maximum_titles=1)


def test_collection_deadline_blocks_before_decision(monkeypatch):
    times = iter([0, 0, 3601])
    monkeypatch.setattr(module, 'review_decision', lambda *args: pytest.fail('Expired scan made decision'))
    with pytest.raises(ScheduledScanBlocked, match='deadline'):
        plan(lambda lib: LibraryScan(True, []), timer=lambda: next(times))


@pytest.mark.parametrize('kwargs', [{'libraries': []}, {'libraries': ['Movies', 'Movies']},
    {'maximum_actions': 0}, {'maximum_actions': True}, {'maximum_titles': -1},
    {'maximum_scan_seconds': float('nan')}, {'revision': True}, {'favorites_trigger_keep': 'false'}])
def test_invalid_policy_never_calls_collector(kwargs):
    with pytest.raises(ValueError):
        plan(lambda lib: pytest.fail('Invalid policy scanned'), **kwargs)


def test_string_protection_flags_are_not_truthy_permissions():
    with pytest.raises(ScheduledScanBlocked, match='invalid_protection'):
        plan(lambda lib: LibraryScan(True, [title(signals={'protected': 'false'})]))


def test_ordinary_scan_does_not_mutate_tracking_or_collector_inputs():
    snapshot = state(); before = deepcopy(snapshot)
    signals = {'favorite': False}; before_signals = dict(signals)
    result = plan(lambda lib: LibraryScan(True, [title(signals=signals)] if lib == 'Movies' else []),
                  snapshot=snapshot)
    assert result.moves[0].destination_stage == 'Holding'
    assert snapshot == before and signals == before_signals


def test_empty_successful_libraries_produce_empty_advisory_plan():
    result = plan(lambda lib: LibraryScan(True, []))
    assert result.scanned_titles == 0 and result.moves == ()
    assert result.authorization == 'not_authorized'
