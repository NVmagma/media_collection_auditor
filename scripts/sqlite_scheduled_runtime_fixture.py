"""Candidate production cycle internals against marked disposable HTTP/media/state.

The production entry remains sealed; this standalone acceptance fixture explicitly
constructs every path/credential and calls only private candidate internals.
"""
from datetime import timedelta
import json
import sys
import unittest
from unittest.mock import patch

from app.sqlite_lock import audit_run_lock
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_scheduled_production import _configured_cycle_step
from app.sqlite_scheduled_worker_cycle import ScheduledWorkerCycle
from scripts.sqlite_scheduled_worker_layout_fixture import WorkerLayoutFixtureTests
from scripts.sqlite_scheduled_configured_slot_fixture import NOW


@unittest.skipUnless(sys.platform == 'linux', 'Actual no-replace rename requires Linux')
class ScheduledRuntimeFixtureTests(unittest.TestCase):
    def setUp(self):
        self.layout = WorkerLayoutFixtureTests(); self.layout.setUp()
        self.addCleanup(self.layout.doCleanups)
        self.values = dict(self.layout.case.values)
        self.source = self.layout.root / 'legacy.json'
        self.original_json = b'{"fixture_legacy_state":"unchanged"}\n'
        self.source.write_bytes(self.original_json)
        self.values.update(STATE_FILE=str(self.source),
                           SQLITE_STATE_FILE=str(self.layout.control / 'state.db'))
        self.cycle = ScheduledWorkerCycle()
        self.slot = self.layout.case.fixture.slot
        self.step(self.slot - timedelta(hours=1))

    def step(self, now):
        return _configured_cycle_step(cycle=self.cycle, settings=self.values, now=now, clock=lambda: NOW)

    def test_startup_and_early_manual_wakes_never_open_a_run(self):
        for seconds in (3000, 1000, 1):
            self.assertEqual(self.step(self.slot - timedelta(seconds=seconds)).status, 'waiting')
        self.assertEqual(self.layout.case.server.calls, [])
        self.assertFalse(self.layout.claims())
        self.assertEqual(self.layout.store.load_with_revision(), self.layout.before)

    def test_due_daily_cycle_executes_both_libraries_and_keeps_json_unchanged(self):
        result = self.step(self.slot + timedelta(seconds=1))
        self.assertEqual(result.status, 'attempted')
        self.assertEqual(len(result.outcome['completed']), 2)
        self.assertEqual(len(self.layout.case.server.calls), 7)
        self.assertEqual(self.source.read_bytes(), self.original_json)
        self.assertEqual(len(self.layout.claims()), 1)
        self.assertEqual(self.step(self.slot + timedelta(seconds=2)).status, 'waiting')
        self.assertEqual(len(self.layout.case.server.calls), 7)

    def test_missed_daily_slot_and_restart_never_catch_up(self):
        self.assertEqual(self.step(self.slot + timedelta(seconds=60)).status, 'missed_slot_skipped')
        self.cycle = ScheduledWorkerCycle()
        self.assertEqual(self.step(self.slot + timedelta(seconds=61)).status, 'waiting')
        self.assertFalse(self.layout.claims())
        self.assertEqual(self.layout.case.server.calls, [])

    def test_shared_json_lock_blocks_before_claim_collection_or_move(self):
        with audit_run_lock(self.source):
            with self.assertRaisesRegex(RuntimeError, 'Nested auditor'):
                self.step(self.slot)
        self.assertFalse(self.layout.claims())
        self.assertEqual(self.layout.case.server.calls, [])
        self.assertEqual(self.layout.store.load_with_revision(), self.layout.before)

    def test_uncertain_move_retains_control_intent_and_blocks_next_day_before_http(self):
        import app.sqlite_scheduled_routed_batch as batch
        rename = batch.rename_directory_noreplace_at
        def uncertain(*args):
            rename(*args)
            raise RuntimeError('fixture uncertain rename')
        with patch.object(batch, 'rename_directory_noreplace_at', uncertain):
            result = self.step(self.slot)
        self.assertEqual(result.outcome['status'], 'stopped')
        self.assertIn(INTENTS_KEY, self.layout.store.load_with_revision()[0])
        calls = len(self.layout.case.server.calls)
        with self.assertRaisesRegex(RuntimeError, 'Unresolved SQLite operation'):
            self.step(self.cycle.next_run)
        self.assertEqual(len(self.layout.case.server.calls), calls)
        self.assertEqual(self.source.read_bytes(), self.original_json)
        self.assertEqual(len(self.layout.claims()), 2)

    def test_clock_rewind_cannot_replay_the_claimed_local_date(self):
        self.step(self.slot)
        calls = len(self.layout.case.server.calls)
        self.step(self.slot - timedelta(minutes=30))
        with self.assertRaises(FileExistsError):
            self.step(self.slot)
        self.assertEqual(len(self.layout.case.server.calls), calls)
        self.assertEqual(len(self.layout.claims()), 1)

    def test_replaced_candidate_database_is_not_adopted(self):
        def replace():
            self.layout.case.server.on_request = None
            database = self.layout.control / 'state.db'
            content = database.read_bytes()
            database.rename(self.layout.control / 'original.db')
            database.write_bytes(content)
        self.layout.case.server.on_request = replace
        with self.assertRaises(RuntimeError):
            self.step(self.slot)
        self.assertEqual(self.layout.store.load_with_revision(), self.layout.before)
        self.assertTrue(all(self.layout.case.fixture.fixture.path(i, 'transient').is_dir() for i in (0, 1)))

    def test_invalid_database_binding_never_claims_or_requests(self):
        self.values['SQLITE_STATE_FILE'] = str(self.source)
        with self.assertRaises(ValueError):
            self.step(self.slot)
        self.assertFalse(self.layout.claims())
        self.assertEqual(self.layout.case.server.calls, [])
        self.assertEqual(self.source.read_bytes(), self.original_json)


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ScheduledRuntimeFixtureTests))
    if not result.wasSuccessful() or result.testsRun != 8 or result.skipped:
        raise SystemExit(1)
    print(json.dumps({'status': 'scheduled_runtime_verified', 'tests': result.testsRun,
        'fixture_only': True, 'production_authorized': False, 'production_activation': 'disabled'}))
