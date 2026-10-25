"""Ephemeral observations plus real sealed-candidate HTTP/media integration."""
from datetime import datetime, timedelta, timezone
import json
import sys
import unittest
from unittest.mock import patch

from app.sqlite_scheduled_observations import ScheduledRunObservations
from app.sqlite_scheduled_production import _configured_cycle_step
from scripts.sqlite_scheduled_arr_fixture import ScheduledArrFixtureTests

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)


class CoordinatorObservationTests(unittest.TestCase):
    def setUp(self): self.observer = ScheduledRunObservations(clock=lambda: NOW)

    def test_restart_has_no_reconstructed_completed_history(self):
        self.assertEqual(self.observer.report()['status'], 'unavailable')
        self.assertIsNone(self.observer.report()['last_result'])
        self.assertEqual(self.observer.history(), [])

    def test_waiting_observation_is_not_a_completed_scan(self):
        self.observer.observe_cycle(next_run=NOW + timedelta(days=1), status='waiting')
        report = self.observer.report()
        self.assertFalse(report['running']); self.assertFalse(report['queued'])
        self.assertFalse(report['freshness_verified']); self.assertIsNone(report['last_result'])
        self.assertFalse(report['history_persistent'])

    def test_running_report_has_no_prior_completion(self):
        def execute():
            report = self.observer.report()
            self.assertTrue(report['running']); self.assertIsNone(report['last_result'])
            self.assertIsNone(report['last_finished'])
            return {'status': 'disposable_scheduled_routed_slot_complete', 'completed': (), 'final_revision': 2}
        self.observer.run_attempt(scheduled_at=NOW, execute=execute)
        self.assertEqual(self.observer.report()['last_result'], 'completed')
        self.assertEqual(self.observer.report()['state_revision'], 2)
        self.assertFalse(self.observer.report()['freshness_verified'])

    def test_exception_text_and_private_payload_never_escape_history(self):
        def execute(): raise RuntimeError('secret-token private-url private-title')
        with self.assertRaises(RuntimeError): self.observer.run_attempt(scheduled_at=NOW, execute=execute)
        text = json.dumps(self.observer.history()) + json.dumps(self.observer.report())
        self.assertNotIn('secret-token', text); self.assertNotIn('private-title', text)
        self.assertEqual(self.observer.report()['last_result'], 'failed')
        self.assertFalse(self.observer.report()['running'])
        self.assertEqual(self.observer.history()[0]['result_basis'], 'blocked_or_uncertain')

    def test_stopped_worker_is_not_reported_as_completed(self):
        self.observer.run_attempt(scheduled_at=NOW,
            execute=lambda: {'status': 'stopped', 'completed': ({'secret': 'do-not-store'},)})
        self.assertEqual(self.observer.report()['last_result'], 'failed')
        self.assertEqual(self.observer.report()['moves_completed'], 1)
        self.assertNotIn('do-not-store', json.dumps(self.observer.history()))

    def test_history_is_bounded_detached_and_restart_local(self):
        for _ in range(102):
            self.observer.run_attempt(scheduled_at=NOW, execute=lambda: {'status': 'stopped'})
        history = self.observer.history()
        self.assertEqual(len(history), 100)
        history[0]['result'] = 'changed'
        self.assertEqual(self.observer.history(1)[0]['result'], 'failed')
        self.assertEqual(self.observer.history(0), [])
        self.assertEqual(ScheduledRunObservations().history(), [])


@unittest.skipUnless(sys.platform == 'linux', 'Actual candidate worker moves require Linux')
class CoordinatorWorkerTests(unittest.TestCase):
    def setUp(self):
        self.case = ScheduledArrFixtureTests(); self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.observer = ScheduledRunObservations(clock=lambda: NOW)
        original = _configured_cycle_step
        def observed(**kwargs): return original(**kwargs, observer=self.observer)
        self.patcher = patch('scripts.sqlite_scheduled_runtime_fixture._configured_cycle_step', observed)
        self.patcher.start(); self.addCleanup(self.patcher.stop)

    def test_real_worker_records_moves_and_arr_without_live_freshness_claim(self):
        self.case.due()
        report = self.observer.report()
        self.assertEqual(report['last_result'], 'completed')
        self.assertEqual(report['moves_completed'], 2)
        self.assertEqual(report['state_revision'], self.case.server.store.load_with_revision()[1])
        self.assertEqual(self.observer.history()[0]['arr_completed'], 2)
        self.assertFalse(report['freshness_verified']); self.assertFalse(report['queued'])
        self.assertFalse(report['running'])
        self.assertEqual(self.case.case.case.source.read_bytes(), self.case.case.case.original_json)

    def test_lost_ack_records_failed_not_completed_or_retryable(self):
        self.case.server.mode = 'lost-ack'
        with self.assertRaises(RuntimeError): self.case.due()
        report = self.observer.report()
        self.assertEqual(report['last_result'], 'failed')
        self.assertEqual(report['scheduler_state'], 'blocked')
        self.assertIsNone(report['state_revision'])
        self.assertFalse(report['running'])
        self.case.no_repeat()
        self.assertEqual(len(self.observer.history()), 1)

    def test_invalid_settings_clear_next_run_without_legacy_fallback(self):
        self.case.case.case.values['SQLITE_DAILY_RUN_TIME'] = 'invalid'
        with self.assertRaises(ValueError): self.case.due()
        report = self.observer.report()
        self.assertEqual(report['scheduler_state'], 'blocked')
        self.assertIsNone(report['next_run'])
        self.assertEqual(self.observer.history(), [])
        self.assertEqual(self.case.server.calls, [])

    def test_early_wake_records_next_slot_without_start_or_history(self):
        self.case.case.case.step(self.case.case.case.slot - timedelta(minutes=1))
        report = self.observer.report()
        self.assertEqual(report['scheduler_state'], 'waiting')
        self.assertIsNotNone(report['next_run'])
        self.assertIsNone(report['last_started'])
        self.assertEqual(self.observer.history(), [])
        self.assertEqual(self.case.server.calls, [])


if __name__ == '__main__':
    suite = unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(cls)
        for cls in (CoordinatorObservationTests, CoordinatorWorkerTests)])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful() or result.testsRun != 10 or result.skipped: raise SystemExit(1)
    print(json.dumps({'status': 'scheduled_coordinator_verified', 'tests': result.testsRun,
        'history_scope': 'current_process', 'freshness_verified': False,
        'fixture_only': True, 'production_authorized': False, 'production_activation': 'disabled'}))
