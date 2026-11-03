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
