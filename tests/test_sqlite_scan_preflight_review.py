from pathlib import Path
from unittest.mock import Mock

import pytest

from app import sqlite_live_binding as live, sqlite_release_profile as build
from app.sqlite_live_policy import DISABLED
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.state_store import GuardedSQLiteStateStore
from scripts.sqlite_preview_release_fixture import prepare_case
from scripts import sqlite_scan_preflight_review as diagnostic
from scripts.sqlite_scheduled_configured_slot_fixture import NOW


@pytest.fixture
def bound(monkeypatch):
    case, source, control, saved, values = prepare_case()
    monkeypatch.setattr(build, 'PROFILE', live.PROFILE)
    monkeypatch.setattr(build, 'SOURCE_REVISION', 'b' * 40)
    values.update(DRY_RUN='false', MAX_ACTIONS_PER_RUN='2',
        **{key: 'false' for key in DISABLED})
    live.create_live_binding(settings=values)
    # Fixture lifecycle dates are deterministic, not the machine's wall clock.
    class Clock:
        @staticmethod
        def now(): return NOW
    monkeypatch.setattr(diagnostic, 'datetime', Clock)
    try: yield case, source, control, saved, values
    finally: case.doCleanups()


def test_real_collection_prepares_without_state_claim_or_media_writes(bound):
    case, source, control, saved, values = bound
    files = [source, saved, control/'state.db']
    before = {path: path.read_bytes() for path in files}
    # The diagnostic must never call persistence, including when discovery is needed.
    from unittest.mock import patch
    with patch.object(GuardedSQLiteStateStore, 'save_if_revision', side_effect=AssertionError('No writes')):
        report = diagnostic.diagnose(settings=values)
    assert report['status'] == 'scan_preflight_reads_complete', report
    assert report['proposed_moves'] == 2
    assert report['scanned_titles'] == 2
    assert report['arr_requests_prepared'] == 0
    assert report['historical_failure_reconstructed'] is False
    assert {path: path.read_bytes() for path in files} == before
    assert not (control/'.sqlite_scheduled_slots').exists()
    assert all(path.exists() for path in (case.fixture.fixture.path(0, 'transient'),
                                        case.fixture.fixture.path(1, 'transient')))


@pytest.mark.parametrize('stage', ['scan_preparation', 'arr_catalog_resolution'])
def test_failing_stage_is_reported_without_private_exception_text(bound, monkeypatch, stage):
    _, _, control, _, values = bound
    failure = Mock(side_effect=RuntimeError('private-token-secret-url-payload'))
    name = 'prepare_scheduled_worker' if stage == 'scan_preparation' else 'configured_arr_queue_resolver'
    monkeypatch.setattr(diagnostic, name, failure)
    before = (control/'state.db').read_bytes()
    report = diagnostic.diagnose(settings=values)
    assert report['status'] == 'scan_preflight_review_blocked'
    assert report['diagnostic_stage'] == stage
    assert report['error_type'] == 'RuntimeError'
    assert 'private-token' not in str(report)
    assert (control/'state.db').read_bytes() == before


def test_pending_intent_blocks_before_any_collection(bound, monkeypatch):
    _, _, control, _, values = bound
    store = GuardedSQLiteStateStore(control/'state.db')
    state, revision = store.load_with_revision()
    state[INTENTS_KEY] = {'kind': 'arr_sync', 'phase': 'intent_recorded'}
    store.save_if_revision(state, revision)
    fetch = Mock(side_effect=AssertionError('No HTTP'))
    monkeypatch.setattr(diagnostic, '_configured_run_inputs', fetch)
    report = diagnostic.diagnose(settings=values)
    assert report['diagnostic_stage'] == 'pending_operation_check'
    fetch.assert_not_called()


def test_comparison_mode_keeps_real_preparation_read_only(bound, monkeypatch):
    _, _, control, _, values = bound
    resolver = Mock(side_effect=AssertionError('No execution request construction'))
    monkeypatch.setattr(diagnostic, 'configured_arr_queue_resolver', resolver)
    before = (control/'state.db').read_bytes()
    report = diagnostic.diagnose(settings=values, compare_arr_paths=True)
    assert report['status'] == 'selected_arr_paths_observed'
    assert len(report['candidates']) == 2
    assert {row['library'] for row in report['candidates']} == {'Movies', 'TV'}
    assert all(row['status'] == 'arr_integration_disabled' for row in report['candidates'])
    assert report['execution_verified'] is False
    assert (control/'state.db').read_bytes() == before
    resolver.assert_not_called()


@pytest.mark.parametrize('kind', ['missing', 'other_root', 'exact'])
def test_selected_path_comparison_reports_only_capped_candidates(bound, monkeypatch, kind):
    _, _, control, _, values = bound
    for prefix in ('RADARR', 'SONARR'):
        values[prefix + '_URL'] = 'http://synthetic.invalid'
        values[prefix + '_API_KEY'] = 'synthetic-private-token'
    # Test the GET-only comparison helper against a synthetic selected plan.
    from types import SimpleNamespace
    prepared = SimpleNamespace(
        bindings=(SimpleNamespace(media_key='TV/Selected', folder='Selected', library='TV'),),
        configuration=SimpleNamespace(libraries=(SimpleNamespace(name='TV',
            roots=(('Waiting', '/media/TV'),)),)),
        plan=SimpleNamespace(moves=(SimpleNamespace(media_key='TV/Selected',
            source_stage='Waiting', destination_stage='Holding'),)))
    records = [{'id': 99, 'path': '/media/TV/Unrelated', 'monitored': True}]
    if kind != 'missing':
        records.append({'id': 7, 'path': ('/other' if kind == 'other_root' else '/media/TV') + '/Selected/',
            'monitored': True})
    fetch = Mock(return_value=records)
    factory = Mock(return_value=fetch)
    monkeypatch.setattr(diagnostic, 'ArrCatalogGET', factory)
    before = (control/'state.db').read_bytes()
    rows = diagnostic.selected_arr_paths(settings=values, prepared=prepared)
    assert len(rows) == 1 and rows[0]['title'] == 'Selected'
    assert rows[0]['matching_records'] == (0 if kind == 'missing' else 1)
    assert rows[0]['status'] == ('exact_source_match' if kind == 'exact' else 'source_missing_or_changed')
    assert 'Unrelated' not in str(rows) and 'synthetic-private-token' not in str(rows)
    factory.assert_called_once()
    assert (control/'state.db').read_bytes() == before
