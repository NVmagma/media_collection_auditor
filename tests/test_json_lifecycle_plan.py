"""Apply the lifecycle rules while skipping titles that Arr does not manage."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime

import pytest
from app.json_lifecycle_plan import LibraryObservation, TitleObservation, plan_scan
from app.lifecycle_decisions import decide
from app.scan_details import reason_code
from test_json_tracking_store import state

NOW = datetime(2026,1,20,12)
SIGNALS = dict(played=True, favorite=False, disliked=True, keep=False, keep_all=False, protected=False)


def title(key='Movie', **changes):
    return replace(TitleObservation(key,'Waiting',30,deepcopy(SIGNALS),'exact_source_match'), **changes)


def library(name='Movies', *titles, **changes):
    return replace(LibraryObservation(name,True,True,tuple(titles)), **changes)


def plan(snapshot=None, libraries=None, **changes):
    return plan_scan(snapshot=snapshot or state(), libraries=libraries or [library('Movies',title())], now=NOW, **changes)


def test_one_slot_per_library_skips_missing_arr_and_selects_next_eligible_title():
    snapshot = state()
    for key in ('Missing','Later','TV/Missing','TV/Later'): snapshot['first_seen'][key] = '2026-01-01'
    libs = [library('Movies',title('Missing',arr_status='missing_record'),title(),title('Later')),
        library('TV',title('TV/Missing',arr_status='path_conflict'),title('TV/Show'),title('TV/Later'))]
    before = deepcopy((snapshot,libs))
    result = plan(snapshot,libs)
    assert [row.media_key for row in result['moves']] == ['Movie','TV/Show']
    assert [row.reason for row in result['decisions']] == [
        'arr_record_missing','disliked','action_cap','arr_path_conflict','disliked','action_cap']
    assert (snapshot,libs) == before
    assert not result['media_actions_authorized'] and not result['permanent_deletion_authorized']


@pytest.mark.parametrize('field', ['keep','protected','favorite'])
@pytest.mark.parametrize('lib,key', [('Movies','Movie'),('TV','TV/Show')])
def test_tags_and_favorites_keep_entire_title(field,lib,key):
    signal = {**SIGNALS, field:True}
    row, = plan(libraries=[library(lib,title(key,signals=signal))])['moves']
    assert row.destination == 'Keep'
    assert row.reason == {'keep':'keep_tag','protected':'protected','favorite':'favorite'}[field]


def test_favorites_disabled_keeps_tag_policy_and_keep_stage_never_prunes():
    assert plan(libraries=[library('Movies',title(signals={**SIGNALS,'favorite':True}))],
        favorites_trigger_keep=False)['moves'][0].destination == 'Holding'
    snapshot = state(); snapshot['first_seen'].pop('TV/Show'); snapshot['keep_seen']['TV/Show'] = '2026-01-01'
    result = plan(snapshot,[library('TV',title('TV/Show',stage='Keep',signals={**SIGNALS,'keep_all':True}))])
    assert not result['moves'] and result['decisions'][0].reason == 'no_transition'


@pytest.mark.parametrize('field,reason', [('jellyfin_complete','jellyfin_collection_incomplete'),
                                         ('arr_complete','arr_catalog_unavailable')])
def test_service_failure_blocks_only_affected_library(field,reason):
    result = plan(libraries=[library('Movies',title(),**{field:False}),library('TV',title('TV/Show'))])
    assert [row.library for row in result['moves']] == ['TV']
    assert result['decisions'][0].reason == reason


@pytest.mark.parametrize('arr,reason', [('missing_record','arr_record_missing'),
    ('ambiguous_record','arr_record_ambiguous'),('path_conflict','arr_path_conflict'),('unavailable','arr_catalog_unavailable')])
def test_arr_problem_never_proposes_move(arr,reason):
    result = plan(libraries=[library('Movies',title(arr_status=arr))])
    assert not result['moves'] and result['decisions'][0].reason == reason


def test_unknown_signals_missing_dates_and_removal_never_authorize_actions():
    assert not plan(libraries=[library('Movies',title(signals=None))])['moves']
    snapshot = state(); snapshot['first_seen'].pop('Movie')
    assert plan(snapshot)['decisions'][0].reason == 'missing_or_conflicting_clock'
    snapshot['in_removal']['Movie'] = '2026-01-01'
    result = plan(snapshot,[library('Movies',title(stage='Removal'))])
    assert not result['moves'] and result['decisions'][0].reason == 'deletion_not_authorized'


def test_all_decisions_retained_beyond_100_without_mutating_dates():
    snapshot = state(); rows=[]
    for i in range(541):
        key = f'Title {i:03}'; snapshot['first_seen'][key] = '2026-01-01'
        rows.append(title(key,signals={**SIGNALS,'disliked':False}))
    before = deepcopy(snapshot)
    result = plan(snapshot,[library('Movies',*rows)])
    assert result['scanned_titles'] == len(result['decisions']) == 541
    assert snapshot == before
    with pytest.raises(RuntimeError): plan(snapshot,[library('Movies',*rows)],maximum_titles=540)


@pytest.mark.parametrize('stage,section', [('Waiting','first_seen'),('Holding','queued'),('Keep','keep_seen')])
@pytest.mark.parametrize('flags', [{}, {'keep':True}, {'protected':True}, {'favorite':True}, {'disliked':False}])
def test_reuses_existing_policy_and_reason_contract(stage,section,flags):
    snapshot = state(); snapshot['first_seen'].pop('Movie'); snapshot[section]['Movie'] = '2026-01-01'
    signal = {**SIGNALS,**flags}
    outcome,explanation=decide(stage,19,30,signal,True)
    expected={'explanation':explanation}
    row, = plan(snapshot,[library('Movies',title(stage=stage,signals=signal))])['decisions']
    assert row.reason == reason_code(expected)


@pytest.mark.parametrize('observation', [title(signals={'disliked':True}), title('../unsafe'), title('.deletedByTMM'), title('TV/Show')])
def test_incomplete_or_unsafe_inputs_refuse_entire_plan(observation):
    with pytest.raises(ValueError): plan(libraries=[library('Movies',observation)])


def test_unresolved_journal_refuses_planning():
    snapshot = state(); snapshot['json_worker_control'] = {'journal':{'kind':'move'}}
    with pytest.raises(RuntimeError): plan(snapshot)


def test_incomplete_library_never_uses_its_apparently_valid_title():
    result = plan(libraries=[library('Movies',title(), jellyfin_complete=False)])
    assert not result['moves'] and result['scanned_titles'] == 1


def test_duplicate_media_identity_never_returns_a_partial_plan():
    with pytest.raises(ValueError): plan(libraries=[library('Movies',title(),title())])


def test_staged_seasons_prevent_whole_show_actions_without_blocking_movies():
    snapshot = state()
    snapshot['tv_leaving_soon_seasons'] = {'TV/Show/1': {}}
    result = plan(snapshot, [library('Movies', title()), library('TV', title('TV/Show'))])
    assert [row.media_key for row in result['moves']] == ['Movie']
    assert result['decisions'][1].reason == 'staged_tv_seasons'
