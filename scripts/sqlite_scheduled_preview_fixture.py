"""Daily dry-run acceptance using new SQLite/media and private HTTP fixtures."""
from datetime import timedelta
import json
import unittest
from unittest.mock import patch

from app.sqlite_lock import audit_run_lock
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_scheduled_observations import ScheduledRunObservations
from app.sqlite_scheduled_production import _configured_cycle_step
from app.sqlite_scheduled_production import _run_bound_production_slot
from app.sqlite_scheduled_worker_cycle import ScheduledWorkerCycle
from scripts import sqlite_scheduled_worker_layout_fixture as layout_fixture
from scripts.sqlite_scheduled_configured_slot_fixture import NOW


class ScheduledPreviewFixtureTests(unittest.TestCase):
    def setUp(self):
        self.layout = layout_fixture.WorkerLayoutFixtureTests(); self.layout.setUp()
        self.addCleanup(self.layout.doCleanups)
        self.values = dict(self.layout.case.values, DRY_RUN='true')
        self.source = self.layout.root / 'legacy.json'
        self.source.write_bytes(b'{"fixture":"unchanged"}\n')
        self.values.update(STATE_FILE=str(self.source),
            SQLITE_STATE_FILE=str(self.layout.control / 'state.db'))
        self.slot = self.layout.case.fixture.slot
        self.cycle = ScheduledWorkerCycle()
        self.observer = ScheduledRunObservations()
        self.step(self.slot - timedelta(hours=1))

    def step(self, now):
        return _configured_cycle_step(cycle=self.cycle, settings=self.values,
            now=now, clock=lambda: NOW, observer=self.observer)

    def assert_unchanged(self, expected=None):
        self.assertEqual(self.layout.store.load_with_revision(),
            self.layout.before if expected is None else expected)
        self.assertEqual(self.source.read_bytes(), b'{"fixture":"unchanged"}\n')
        self.assertTrue(all(self.layout.case.fixture.fixture.path(i, 'transient').is_dir()
            for i in (0, 1)))
        self.assertFalse(any(self.layout.case.fixture.fixture.path(i, 'holding').exists()
            for i in (0, 1)))

    def test_due_preview_collects_both_libraries_without_dispatch_or_state_write(self):
        with (patch('app.sqlite_scheduled_production.configured_arr_queue_resolver',
                side_effect=AssertionError('No Arr lookup in preview')),
            patch('app.sqlite_scheduled_production._run_routed_slot_locked',
                side_effect=AssertionError('No dispatch in preview')),
            patch('app.sqlite_audit_session.RevisionedAuditSession.checkpoint',
                side_effect=AssertionError('No checkpoint in preview'))):
            report = self.step(self.slot).outcome
        self.assertEqual(report['status'], 'scheduled_preview_complete')
        self.assertEqual(len(report['proposed_moves']), 2)
        self.assertEqual(report['completed'], ())
        self.assertEqual(len(self.layout.case.server.calls), 4)
        self.assert_unchanged()
        history = self.observer.history()[0]
        self.assertTrue(history['dry_run'])
        self.assertEqual(history['result'], 'completed')
        self.assertEqual(history['moves_completed'], 0)

    def test_discovery_proposals_never_checkpoint_or_masquerade_as_empty_success(self):
        state, revision = self.layout.store.load_with_revision()
        state['first_seen'].clear()
        self.layout.store.save_if_revision(state, revision)
        expected = self.layout.store.load_with_revision()
        report = self.step(self.slot).outcome
        self.assertGreater(report['discovery_changes'], 0)
        self.assertTrue(report['discovery_checkpoint_required'])
        self.assertEqual(report['proposed_moves'], ())
        self.assertFalse(report['clock_checkpointed'])
        self.assert_unchanged(expected)

    def test_failed_collection_is_failed_history_with_retained_claim(self):
        self.layout.case.server.mode = 'unauthorized'
        with self.assertRaises(Exception):
            self.step(self.slot)
        self.assertEqual(self.observer.history()[0]['result'], 'failed')
        self.assertTrue(self.observer.history()[0]['dry_run'])
        self.assertEqual(len(self.layout.claims()), 1)
        self.assert_unchanged()

    def test_pending_operation_stops_before_http(self):
        state, revision = self.layout.store.load_with_revision()
        state[INTENTS_KEY] = {}
        self.layout.store.save_if_revision(state, revision)
        expected = self.layout.store.load_with_revision()
        with self.assertRaisesRegex(RuntimeError, 'Unresolved SQLite operation'):
            self.step(self.slot)
        self.assertEqual(self.layout.case.server.calls, [])
        self.assert_unchanged(expected)

    def test_database_replacement_during_collection_is_not_adopted(self):
        def replace():
            self.layout.case.server.on_request = None
            path = self.layout.control / 'state.db'
            content = path.read_bytes()
            path.rename(self.layout.control / 'original.db')
            path.write_bytes(content)
        self.layout.case.server.on_request = replace
        with self.assertRaises(RuntimeError):
            self.step(self.slot)
        self.assertEqual(self.observer.history()[0]['result'], 'failed')

    def test_shared_lock_blocks_before_claim_or_http(self):
        with audit_run_lock(self.source):
            with self.assertRaisesRegex(RuntimeError, 'Nested auditor'):
                self.step(self.slot)
        self.assertFalse(self.layout.claims())
        self.assertEqual(self.layout.case.server.calls, [])

    def test_mode_toggle_cannot_reuse_preview_daily_claim(self):
        self.step(self.slot)
        self.values['DRY_RUN'] = 'false'
        self.cycle = ScheduledWorkerCycle()
        self.step(self.slot - timedelta(seconds=1))
        calls = len(self.layout.case.server.calls)
        with self.assertRaises(FileExistsError):
            self.step(self.slot)
        self.assertEqual(len(self.layout.case.server.calls), calls)
        self.assert_unchanged()

    def test_global_action_cap_applies_to_advisory_moves(self):
        self.values['MAX_ACTIONS_PER_RUN'] = '1'
        report = self.step(self.slot).outcome
        self.assertEqual(len(report['proposed_moves']), 1)
        self.assertEqual(report['scanned_titles'], 2)
        self.assert_unchanged()

    def test_later_library_failure_never_returns_first_library_partial_plan(self):
        def fail_tv():
            if len(self.layout.case.server.calls) == 3:
                self.layout.case.server.mode = 'unauthorized'
        self.layout.case.server.on_request = fail_tv
        with self.assertRaisesRegex(RuntimeError, 'protection unavailable'):
            self.step(self.slot)
        self.assertEqual(self.observer.history()[0]['result'], 'failed')
        self.assert_unchanged()

    def test_one_deadline_includes_claim_and_collection(self):
        ticks = [0.0]
        self.layout.case.server.on_request = lambda: ticks.__setitem__(0, 3601.0)
        with self.assertRaises(RuntimeError):
            _run_bound_production_slot(settings=self.values, scheduled_at=self.slot,
                now=self.slot, clock=lambda: NOW, timer=lambda: ticks[0])
        self.assertEqual(len(self.layout.claims()), 1)
        self.assert_unchanged()


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ScheduledPreviewFixtureTests))
    if not result.wasSuccessful() or result.testsRun != 10 or result.skipped:
        raise SystemExit(1)
    print(json.dumps({'status': 'scheduled_preview_verified', 'tests': result.testsRun,
        'fixture_only': True, 'production_authorized': False, 'production_activation': 'disabled'}))
