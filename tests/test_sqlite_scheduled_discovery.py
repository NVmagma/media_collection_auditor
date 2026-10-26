from copy import deepcopy
from datetime import datetime

import pytest

from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_scheduled_discovery import propose_discovery_clocks
from app.sqlite_scheduled_worker import ScheduledTitleBinding
from app.sqlite_state import SECTIONS

NOW = datetime(2026, 10, 24)
OLD = datetime(2026, 1, 1)
NEW = datetime(2026, 10, 1)


def binding(stage='Waiting', tv=False):
    return ScheduledTitleBinding('TV' if tv else 'Movies', 'TV/A' if tv else 'A', 'A',
                                 stage, 'Series' if tv else 'Movie')


def state():
    result = {section: {} for section in SECTIONS}
    result['custom'] = {'preserve': [1, 2]}
    return result


def propose(snapshot, bindings=None, **kwargs):
    bindings = [binding()] if bindings is None else bindings
    return propose_discovery_clocks(snapshot=snapshot, revision=7, bindings=bindings, now=NOW,
        available_protection_keys=kwargs.pop('available_protection_keys', {b.media_key for b in bindings}), **kwargs)


@pytest.mark.parametrize('stage,section', [('Waiting', 'first_seen'), ('Holding', 'queued'),
                                         ('Keep', 'keep_seen'), ('Removal', 'in_removal')])
def test_new_titles_start_at_observation_time_in_actual_stage(stage, section):
    snapshot = state(); before = deepcopy(snapshot)
    result = propose(snapshot, [binding(stage)])
    assert result.proposed_snapshot[section] == {'A': NOW.isoformat()}
    assert result.source_snapshot == before and snapshot == before
    assert result.source_revision == 7 and result.authorization == 'not_authorized'
    assert result.proposed_snapshot['custom'] == before['custom']


def test_missing_protection_does_not_start_clock():
    result = propose(state(), available_protection_keys=set())
    assert result.changes == () and result.proposed_snapshot['first_seen'] == {}


def test_same_movie_tv_folder_has_distinct_clocks():
    result = propose(state(), [binding(), binding(tv=True)])
    assert set(result.proposed_snapshot['first_seen']) == {'A', 'TV/A'}


def test_existing_tv_clock_only_advances_for_newer_complete_observation():
    snapshot = state(); snapshot['first_seen']['TV/A'] = OLD.isoformat()
    result = propose(snapshot, [binding(tv=True)], reset_keys={'TV/A'}, reset_content_times={'TV/A': NEW})
    assert result.proposed_snapshot['first_seen']['TV/A'] == NEW.isoformat()
    assert result.changes == (('TV/A', 'content_reset', 'first_seen'),)
    assert snapshot['first_seen']['TV/A'] == OLD.isoformat()


@pytest.mark.parametrize('content', [None, OLD, datetime(2025, 1, 1)])
def test_empty_or_older_content_never_rewinds_clock(content):
    snapshot = state(); snapshot['first_seen']['TV/A'] = OLD.isoformat()
    assert propose(snapshot, [binding(tv=True)], reset_keys={'TV/A'},
        reset_content_times={'TV/A': content}).changes == ()


def test_new_series_does_not_inherit_old_filesystem_age():
    result = propose(state(), [binding(tv=True)], reset_keys={'TV/A'}, reset_content_times={'TV/A': OLD})
    assert result.proposed_snapshot['first_seen']['TV/A'] == NOW.isoformat()


def test_missing_enabled_reset_observation_is_rejected():
    with pytest.raises(ValueError, match='completed content'):
        propose(state(), [binding(tv=True)], reset_keys={'TV/A'})


@pytest.mark.parametrize('content', [datetime(2030, 1, 1), '2026-10-01'])
def test_invalid_content_time_blocks_proposal(content):
    with pytest.raises(ValueError, match='content observation'):
        propose(state(), [binding(tv=True)], reset_keys={'TV/A'}, reset_content_times={'TV/A': content})


def test_stage_conflict_is_preserved_and_blocks_instead_of_reconciling():
    snapshot = state(); snapshot['queued']['A'] = OLD.isoformat(); before = deepcopy(snapshot)
    with pytest.raises(RuntimeError, match='stage conflicts'):
        propose(snapshot)
    assert snapshot == before


def test_missing_inventory_titles_are_not_forgotten():
    snapshot = state(); snapshot['first_seen']['Missing'] = OLD.isoformat()
    assert propose(snapshot).proposed_snapshot['first_seen']['Missing'] == OLD.isoformat()


def test_pending_intent_blocks_all_discovery():
    snapshot = state(); snapshot[INTENTS_KEY] = {'id': 'pending'}
    with pytest.raises(ValueError): propose(snapshot)
