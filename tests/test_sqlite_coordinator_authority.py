from unittest.mock import Mock
import pytest
from app import integration_status as module
from app import sqlite_scheduled_observations as observations


def test_sqlite_selection_never_reads_legacy_history_or_coordinator(monkeypatch):
    monkeypatch.setenv('AUDITOR_STATE_BACKEND', 'sqlite')
    legacy = Mock(side_effect=AssertionError('No JSON fallback'))
    report = module.selected_audit_status_report(legacy)
    assert report['status'] == 'unavailable' and report['storage_authority'] == 'sqlite'
    assert report['running'] is None and report['last_result'] is None
    assert module.selected_run_history(legacy) == []
    legacy.assert_not_called()


def test_candidate_observations_are_process_scoped_and_do_not_claim_freshness(monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setenv('AUDITOR_STATE_BACKEND', 'sqlite')
    monkeypatch.setattr(module, '_require_sqlite_authority', lambda: None)  # Test-only candidate seam.
    coordinator = observations.ScheduledRunObservations()
    coordinator.observe_cycle(next_run=datetime.now(timezone.utc), status='waiting')
    monkeypatch.setattr(observations, 'COORDINATOR', coordinator)
    legacy = Mock(side_effect=AssertionError('No legacy reads'))
    report = module.selected_audit_status_report(legacy)
    assert report['source'] == 'sqlite_scheduler_process'
    assert report['history_scope'] == 'current_process'
    assert report['history_persistent'] is False and report['freshness_verified'] is False
    assert report['last_result'] is None and module.selected_run_history(legacy) == []
    legacy.assert_not_called()


def test_json_selection_preserves_existing_coordinator_and_history(monkeypatch):
    monkeypatch.setenv('AUDITOR_STATE_BACKEND', 'json')
    current = {'running': False, 'queued': False, 'rescuing': False, 'last_result': 'completed'}
    assert module.selected_audit_status_report(lambda: current) == module.audit_status_report(current)
    assert module.selected_run_history(lambda limit: [{'legacy': limit}], 1) == [{'legacy': 1}]
