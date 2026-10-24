"""Due daily slot composition using only new marked disposable Linux media."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import signal
import subprocess
import sys
import unittest
from unittest.mock import patch

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_run_schedule import DailyRunSchedule
from app.sqlite_scheduled_recheck import ProtectionRead
from app.sqlite_scheduled_routed_batch import execute_disposable_routed_batch
from app.sqlite_scheduled_routed_slot import run_disposable_routed_slot
from app.state_store import GuardedSQLiteStateStore
from scripts.sqlite_scheduled_routed_fixture import ScheduledRoutedFixtureTests
import app.sqlite_scheduled_routed_batch as batch_module
import app.sqlite_scheduled_slot as slot_module

NOW = datetime(2026, 10, 24)


@unittest.skipUnless(sys.platform == 'linux', 'Actual scheduled renames require Linux')
class ScheduledRoutedSlotFixtureTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ScheduledRoutedFixtureTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.store, self.config = self.fixture.root, self.fixture.store, self.fixture.config
        self.initial, self.revision = self.store.load_with_revision()
        self.slot = self.config.schedule.next_start(datetime(2026, 10, 24, tzinfo=timezone.utc))
        self.events = []

    def scan(self, binding):
        self.events.append('scan:' + binding.library)
        return self.fixture.signals()

    def protection(self, move):
        self.events.append('move:' + move.library)
        return ProtectionRead(True, self.fixture.signals())

    def execute(self, **kwargs):
        slot = kwargs.pop('scheduled_at', self.slot)
        return run_disposable_routed_slot(root=self.root, config=kwargs.pop('config', self.config),
            scheduled_at=slot, now=kwargs.pop('now', slot + timedelta(seconds=10)),
            fetch_signals=kwargs.pop('fetch_signals', self.scan),
            fetch_protection=kwargs.pop('fetch_protection', self.protection),
            clock=kwargs.pop('clock', lambda: NOW), **kwargs)

    def claims(self):
        return sorted((self.root / '.sqlite_scheduled_slots').glob('*.json'))

    def test_due_slot_scans_both_libraries_before_moving_and_retains_claim(self):
        result = self.execute()
        self.assertEqual(result['status'], 'disposable_scheduled_routed_slot_complete')
        self.assertEqual(self.events, ['scan:Movies', 'scan:TV', 'move:Movies', 'move:TV'])
        self.assertEqual(len(result['completed']), 2)
        self.assertFalse(result['clock_checkpointed'])
        self.assertEqual(result['initial_revision'], self.revision)
        self.assertEqual(result['final_revision'], self.revision + 6)
        self.assertEqual(len(self.claims()), 1)
        record = json.loads(self.claims()[0].read_text())
        self.assertFalse(record['automatic_replay'])
        self.assertEqual(record['local_date'], '2026-10-24')
        self.assertFalse(result['production_authorized'])
        self.assertEqual(result['production_activation'], 'disabled')

    def test_same_slot_cannot_recollect_or_replay_after_success(self):
        self.execute(); before = self.store.load_with_revision(); self.events.clear()
        record = self.claims()[0].read_bytes()
        with self.assertRaises(FileExistsError): self.execute()
        self.assertEqual(self.events, [])
        self.assertEqual(self.store.load_with_revision(), before)
        self.assertEqual(self.claims()[0].read_bytes(), record)

    def test_changed_time_on_same_local_date_cannot_create_second_attempt(self):
        self.execute(); before = self.store.load_with_revision(); self.events.clear()
        config = replace(self.config, schedule=DailyRunSchedule('03:00', 'America/Los_Angeles'))
        slot = config.schedule.next_start(datetime(2026, 10, 24, tzinfo=timezone.utc))
        with self.assertRaises(FileExistsError): self.execute(config=config, scheduled_at=slot)
        self.assertEqual(self.events, [])
        self.assertEqual(self.store.load_with_revision(), before)
        self.assertEqual(len(self.claims()), 1)

    def test_early_and_missed_slots_do_not_collect_or_claim(self):
        for offset in (-1, 61):
            with self.subTest(offset=offset):
                with self.assertRaises(RuntimeError): self.execute(now=self.slot + timedelta(seconds=offset))
        self.assertEqual(self.events, [])
        self.assertEqual(self.claims(), [])
        self.assertEqual(self.store.load_with_revision(), (self.initial, self.revision))

    def test_complete_scan_failure_retains_claim_and_does_not_move(self):
        def scan(binding):
            if binding.library == 'TV': raise RuntimeError('fixture collection failure')
            return self.scan(binding)
        with self.assertRaisesRegex(RuntimeError, 'collection failure'): self.execute(fetch_signals=scan)
        self.assertEqual(self.store.load_with_revision(), (self.initial, self.revision))
        self.assertEqual(len(self.claims()), 1)
        self.assertTrue(self.fixture.path(0, 'transient').is_dir())
        self.assertTrue(self.fixture.path(1, 'transient').is_dir())
        self.events.clear()
        with self.assertRaises(FileExistsError): self.execute()
        self.assertEqual(self.events, [])

    def test_discovery_checkpoint_and_rebuild_finish_before_keep_moves(self):
        session = RevisionedAuditSession(self.store); session.state['first_seen'].clear(); session.checkpoint()
        before = session.revision
        def scan(binding):
            self.events.append('scan:' + binding.library)
            return self.fixture.signals(keep=True)
        result = self.execute(fetch_signals=scan,
            fetch_protection=lambda _: ProtectionRead(True, self.fixture.signals(keep=True)))
        self.assertTrue(result['clock_checkpointed'])
        self.assertEqual(self.events, ['scan:Movies', 'scan:TV'] * 2)
        self.assertEqual(result['post_clock_revision'], before + 1)
        state, revision = self.store.load_with_revision()
        self.assertEqual(revision, before + 7)
        self.assertEqual(set(state['keep_seen']), {'Same (2020)', 'TV/Same (2020)'})
        self.assertEqual(state['first_seen'], {})

    def test_one_lock_covers_collection_and_per_move_refresh(self):
        def check_lock():
            with self.assertRaisesRegex(RuntimeError, 'runner is active'):
                execute_disposable_routed_batch(root=self.root, config=self.config,
                    preparation=self.fixture.prepared, fetch_protection=self.protection, clock=lambda: NOW)
        def scan(binding): check_lock(); return self.scan(binding)
        def protect(move): check_lock(); return self.protection(move)
        result = self.execute(fetch_signals=scan, fetch_protection=protect)
        self.assertEqual(result['status'], 'disposable_scheduled_routed_slot_complete')
        self.assertEqual(len(result['completed']), 2)

    def test_global_cap_filters_detached_arr_requests_without_tv_move(self):
        self.config = self.fixture.fixture.config(cap=1)
        requests = {key: {'service': service, 'title_id': number, 'root': '/arr/' + service, 'monitored': False}
                    for key, service, number in [('Same (2020)', 'radarr', 1), ('TV/Same (2020)', 'sonarr', 2)]}
        def scan(binding):
            requests['Same (2020)']['root'] = '/mutated'
            return self.scan(binding)
        result = self.execute(fetch_signals=scan, arr_sync_requests=requests)
        self.assertEqual(result['capped_moves'], 1)
        self.assertEqual(len(result['completed']), 1)
        state, _ = self.store.load_with_revision()
        self.assertEqual(state['arr_sync_pending']['Same (2020)']['root'], '/arr/radarr')
        self.assertNotIn('TV/Same (2020)', state['arr_sync_pending'])
        self.assertTrue(self.fixture.path(1, 'transient').is_dir())

    def test_next_local_date_runs_a_fresh_globally_capped_attempt(self):
        self.config = self.fixture.fixture.config(cap=1)
        first = self.execute()
        next_slot = self.config.schedule.next_start(self.slot)
        # Advance the injected scheduling calendar while keeping lifecycle
        # fixture clocks in the past; production future-clock guards stay intact.
        second = self.execute(scheduled_at=next_slot)
        self.assertEqual(len(first['completed']), 1)
        self.assertEqual(len(second['completed']), 1)
        self.assertEqual(second['completed'][0]['media_key'], 'TV/Same (2020)')
        self.assertEqual(len(self.claims()), 2)
        state, revision = self.store.load_with_revision()
        self.assertEqual(revision, self.revision + 6)
        self.assertEqual(len(state['queued']), 2)

    def test_partial_claim_failure_never_collects_and_is_not_replaced(self):
        with patch.object(slot_module.os, 'write', return_value=0):
            with self.assertRaises(OSError): self.execute()
        self.assertEqual(self.events, [])
        self.assertEqual(len(self.claims()), 1)
        self.assertEqual(self.claims()[0].read_bytes(), b'')
        with self.assertRaises(FileExistsError): self.execute()
        self.assertEqual(self.store.load_with_revision(), (self.initial, self.revision))

    def test_uncertain_clock_commit_retains_claim_and_never_dispatches(self):
        session = RevisionedAuditSession(self.store); session.state['first_seen'].clear(); session.checkpoint()
        before = session.revision
        original = GuardedSQLiteStateStore.save_if_revision; writes = []
        def save(store, state, revision):
            writes.append(revision); original(store, state, revision)
            raise RuntimeError('fixture clock acknowledgement lost')
        with patch.object(GuardedSQLiteStateStore, 'save_if_revision', save):
            with self.assertRaisesRegex(RuntimeError, 'clock acknowledgement lost'): self.execute()
        self.assertEqual(writes, [before])
        state, revision = self.store.load_with_revision()
        self.assertEqual(revision, before + 1)
        self.assertEqual(len(state['first_seen']), 2)
        self.assertFalse(any(event.startswith('move:') for event in self.events))
        with self.assertRaises(FileExistsError): self.execute()
        self.assertEqual(len(self.claims()), 1)

    def test_one_deadline_covers_scan_and_dispatch_without_reset(self):
        tick = [0]
        def scan(binding): tick[0] += 1; return self.scan(binding)
        def protect(move): tick[0] += 1; return self.protection(move)
        with self.assertRaises(RuntimeError):
            self.execute(fetch_signals=scan, fetch_protection=protect, timer=lambda: tick[0], maximum_run_seconds=3)
        self.assertEqual(self.store.load_with_revision(), (self.initial, self.revision))
        self.assertEqual(len(self.claims()), 1)
        self.assertTrue(self.fixture.path(0, 'transient').is_dir())

    def test_pending_move_blocks_even_the_next_dates_attempt(self):
        original = batch_module.rename_directory_noreplace_at
        def rename(*args): original(*args); raise RuntimeError('fixture rename acknowledgement lost')
        with patch.object(batch_module, 'rename_directory_noreplace_at', rename): result = self.execute()
        self.assertEqual(result['status'], 'stopped')
        before = self.store.load_with_revision()
        self.assertIn(INTENTS_KEY, before[0])
        next_slot = self.config.schedule.next_start(self.slot)
        with self.assertRaises(RuntimeError): self.execute(scheduled_at=next_slot)
        self.assertEqual(self.store.load_with_revision(), before)
        self.assertEqual(len(self.claims()), 2)
        self.assertTrue(self.fixture.path(1, 'transient').is_dir())

    def test_actual_controller_sigkill_retains_daily_claim_and_blocks_replay(self):
        script = r"""
import json,sys,os,signal
from datetime import datetime,timedelta,timezone
from app.sqlite_scheduled_worker import configured_scheduled_worker
from app.sqlite_scheduled_routed_slot import run_disposable_routed_slot
from app.sqlite_scheduled_recheck import ProtectionRead
import app.sqlite_scheduled_routed_batch as batch
request=json.load(sys.stdin)
config=configured_scheduled_worker(libraries=request['libraries'],local_time='02:00',timezone_name='America/Los_Angeles',holding_days=7)
slot=config.schedule.next_start(datetime(2026,10,24,tzinfo=timezone.utc))
signals={field:False for field in ('played','favorite','disliked','keep','keep_all','protected')}
original=batch.rename_directory_noreplace_at
def rename(*args):
    original(*args)
    os.kill(os.getpid(),signal.SIGKILL)
batch.rename_directory_noreplace_at=rename
run_disposable_routed_slot(root=request['root'],config=config,scheduled_at=slot,now=slot+timedelta(seconds=10),fetch_signals=lambda _:signals,fetch_protection=lambda _:ProtectionRead(True,signals),clock=lambda:datetime(2026,10,24))
"""
        child = subprocess.run([sys.executable, '-S', '-B', '-c', script],
            input=json.dumps({'root': str(self.root), 'libraries': self.fixture.fixture.libraries}).encode(),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        self.assertEqual(child.returncode, -signal.SIGKILL, child.stderr.decode())
        state, revision = self.store.load_with_revision()
        self.assertEqual(revision, self.revision + 1)
        self.assertEqual(state[INTENTS_KEY]['phase'], 'intent_recorded')
        self.assertEqual(len(self.claims()), 1)
        self.assertTrue(self.fixture.path(0, 'holding').is_dir())
        with self.assertRaises(FileExistsError): self.execute()
        self.assertEqual(self.events, [])
        self.assertEqual(self.store.load_with_revision(), (state, revision))


def main():
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(
        ScheduledRoutedSlotFixtureTests))
    if not result.wasSuccessful() or result.skipped or result.testsRun != 14: return 1
    print(json.dumps({'status': 'scheduled_routed_slot_verified', 'tests': result.testsRun,
        'fixture_only': True, 'production_activation': 'disabled', 'production_authorized': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
