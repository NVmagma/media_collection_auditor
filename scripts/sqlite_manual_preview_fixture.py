"""Explicit read-only scans: actual private HTTP, locks, binding and daily parity."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from app import sqlite_preview_activation as activation, sqlite_release_profile as build
from app.sqlite_lock import audit_run_lock
from app.sqlite_scheduled_observations import ScheduledRunObservations
from app.sqlite_scheduled_production import run_requested_preview, production_cycle_step, _hold_control_database
from app.sqlite_scheduled_worker_cycle import ScheduledWorkerCycle
from app.state_store import GuardedSQLiteStateStore
from scripts.sqlite_preview_release_fixture import prepare_case
from scripts.sqlite_scheduled_configured_slot_fixture import NOW


@unittest.skipUnless(sys.platform=='linux','Linux bound manual preview')
class ManualPreviewTests(unittest.TestCase):
    def setUp(self):
        self.case,self.source,self.control,self.saved,self.values=prepare_case()
        self.addCleanup(self.case.doCleanups)
        for field,value in (('PROFILE',activation.PROFILE),('SOURCE_REVISION','a'*40)):
            override=patch.object(build,field,value); override.start(); self.addCleanup(override.stop)
        activation.create_preview_binding(settings=self.values)
        self.store=GuardedSQLiteStateStore(self.control/'state.db')
        self.before=self.store.load_with_revision()
        self.source_before=self.source.read_bytes()
        self.media_before={str(p):p.read_bytes() for library in self.case.fixture.config.libraries
            for _,root in library.roots for p in Path(root).rglob('*') if p.is_file()}
        self.observer=ScheduledRunObservations()
        self.slot=self.case.fixture.slot
        self.now=self.slot-timedelta(hours=1)
        self.observer.observe_cycle(next_run=self.slot,status='waiting')

    def run_preview(self):
        return run_requested_preview(settings=self.values,now=self.now,observer=self.observer,clock=lambda:NOW)

    def unchanged(self):
        self.assertEqual(self.store.load_with_revision(),self.before)
        self.assertEqual(self.source.read_bytes(),self.source_before)
        for name,raw in self.media_before.items():
            from pathlib import Path
            self.assertEqual(Path(name).read_bytes(),raw)
        self.assertFalse((self.control/'.sqlite_scheduled_slots').exists())

    def test_explicit_off_schedule_scan_reads_both_libraries_without_actions_or_daily_claim(self):
        self.assertTrue(self.observer.request_manual_preview())
        with patch('app.sqlite_scheduled_production._run_routed_slot_locked',side_effect=AssertionError('No actions')), \
             patch('app.sqlite_scheduled_production.configured_arr_queue_resolver',side_effect=AssertionError('No Arr')), \
             patch('app.sqlite_scheduled_production._claim_scheduled_slot_locked',side_effect=AssertionError('No daily claim')):
            result=self.run_preview()
        self.assertEqual(result['status'],'scheduled_preview_complete')
        self.assertEqual(result['completed'],()); self.assertFalse(result['clock_checkpointed'])
        self.assertGreater(len(self.case.server.calls),0)
        self.unchanged()
        row=self.observer.history()[0]
        self.assertEqual(row['trigger'],'manual'); self.assertTrue(row['dry_run'])
        self.assertEqual(row['result'],'completed')
        self.assertEqual(self.observer.report()['next_run'],self.slot.isoformat())
        self.assertFalse(self.observer.report()['queued'])

    def test_without_explicit_request_never_collects(self):
        self.assertIsNone(self.run_preview()); self.assertEqual(self.case.server.calls,[])
        self.assertEqual(self.observer.history(),[]); self.unchanged()

    def test_manual_scan_does_not_consume_the_daily_slot(self):
        cycle=ScheduledWorkerCycle()
        def step(now):
            return production_cycle_step(cycle=cycle,settings=self.values,now=now,
                observer=self.observer,clock=lambda:NOW)
        self.assertEqual(step(self.now).status,'waiting')
        next_run=cycle.next_run
        self.observer.request_manual_preview(); self.run_preview()
        self.assertEqual(cycle.next_run,next_run); self.unchanged()
        due=step(self.slot+timedelta(seconds=1))
        self.assertEqual(due.status,'attempted')
        self.assertEqual(due.outcome['status'],'scheduled_preview_complete')
        self.assertEqual(self.observer.history()[0]['trigger'],'scheduled')
        self.assertEqual(self.observer.history()[1]['trigger'],'manual')
        self.assertEqual(self.store.load_with_revision(),self.before)

    def test_collection_failure_is_redacted_and_not_automatically_retried(self):
        self.case.server.mode='unauthorized'
        self.observer.request_manual_preview()
        with self.assertRaises(RuntimeError): self.run_preview()
        count=len(self.case.server.calls)
        self.assertIsNone(self.run_preview()); self.assertEqual(len(self.case.server.calls),count)
        self.assertEqual(self.observer.report()['last_result'],'failed')
        self.assertNotIn('synthetic-token',json.dumps(self.observer.history()))
        self.unchanged()

    def test_changed_settings_after_queue_blocks_without_collection(self):
        self.observer.request_manual_preview(); self.saved.write_text('{"DRY_RUN":"false"}')
        with self.assertRaises(RuntimeError): self.run_preview()
        self.assertEqual(self.case.server.calls,[])
        self.assertFalse(self.observer.report()['queued'])
        self.assertEqual(self.observer.report()['last_result'],'failed')
        self.unchanged()

    def test_sealed_image_cannot_accept_manual_preview_dispatch(self):
        self.observer.request_manual_preview()
        with patch.object(build,'PROFILE','sealed'):
            with self.assertRaises(RuntimeError): self.run_preview()
        self.assertEqual(self.case.server.calls,[]); self.unchanged()

    def test_manual_request_cannot_dispatch_live_mode(self):
        self.values['DRY_RUN']='false'
        self.observer.request_manual_preview()
        with self.assertRaises(RuntimeError): self.run_preview()
        self.assertEqual(self.case.server.calls,[]); self.unchanged()

    def test_shared_json_lock_blocks_manual_scan_before_http(self):
        self.observer.request_manual_preview()
        with audit_run_lock(self.source):
            with self.assertRaises(RuntimeError): self.run_preview()
        self.assertEqual(self.case.server.calls,[]); self.unchanged()

    def test_shared_sqlite_control_lock_blocks_before_http(self):
        self.observer.request_manual_preview()
        with _hold_control_database(self.control,self.control/'state.db'):
            with self.assertRaises(RuntimeError): self.run_preview()
        self.assertEqual(self.case.server.calls,[]); self.unchanged()

    def test_duplicate_requests_rejected_pending_claimed_and_running(self):
        self.assertTrue(self.observer.request_manual_preview())
        self.assertFalse(self.observer.request_manual_preview())
        self.assertTrue(self.observer.claim_manual_preview())
        self.assertFalse(self.observer.request_manual_preview())
        self.observer.release_manual_preview()
        self.assertTrue(self.observer.request_manual_preview())
        old=self.case.server.on_request if hasattr(self.case.server,'on_request') else None
        def during(): self.assertFalse(self.observer.request_manual_preview())
        self.case.server.on_request=during
        try: self.run_preview()
        finally: self.case.server.on_request=old
        self.unchanged()


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ManualPreviewTests))
    if not result.wasSuccessful() or result.skipped: raise SystemExit(1)
    print(json.dumps({'status':'manual_readonly_preview_verified','tests':result.testsRun,
        'fixture_only':True,'media_actions_authorized':False,'daily_slot_consumed':False}))
