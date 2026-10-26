"""Standard-library acceptance tests using only new disposable Linux media."""
from datetime import datetime, timezone
import errno
import json
import os
from pathlib import Path
import sys
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from app.sqlite_scheduled_disposable_batch import execute_scheduled_disposable_batch
from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_scheduled_plan import LibraryScan, ScannedTitle, collect_scheduled_plan
from app.sqlite_scheduled_recheck import ProtectionRead
from app.sqlite_jellyfin_signal_contract import SIGNAL_FIELDS
from app.sqlite_scheduled_disposable_executor import execute_scheduled_disposable_move
from app.state_store import GuardedSQLiteStateStore
from app.sqlite_state import SECTIONS

NOW = datetime(2024, 2, 1)


@unittest.skipUnless(sys.platform == 'linux', 'Real no-replace rename requires Linux')
class ScheduledMoveFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='scheduled-move-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / '.sqlite_disposable_rehearsal').write_text('DISPOSABLE ONLY\n')
        for stage in ('transient', 'holding', 'keep', 'removal'):
            (self.root / stage).mkdir()
        self.source = self.root / 'transient/Movie'; self.source.mkdir()
        (self.source / 'payload').write_text('disposable original')
        self.destination = self.root / 'holding/Movie'
        self.database = self.root / 'state.db'
        snapshot = {key: {} for key in SECTIONS}
        snapshot['first_seen']['Movie'] = '2024-01-01'
        write_offline_snapshot(snapshot, self.database)
        self.store = GuardedSQLiteStateStore(self.database)
        self.initial, revision = self.store.load_with_revision()
        self.plan = collect_scheduled_plan(snapshot=self.initial, revision=revision,
            libraries=['Movies'], now=NOW, timer=lambda: 100,
            scan_library=lambda _: LibraryScan(True, [ScannedTitle('Movie', 'Waiting', 7, {})]))

    def protection(self, **flags):
        signals = {key: False for key in SIGNAL_FIELDS}; signals.update(flags)
        return ProtectionRead(True, signals)

    def execute(self, **kwargs):
        values = dict(root=self.root, database=self.database, operation_id='scheduled-fixture',
            plan=self.plan, move=self.plan.moves[0], title_folder='Movie',
            fetch_protection=lambda _: self.protection(), clock=lambda: NOW, timer=lambda: 101)
        values.update(kwargs)
        return execute_scheduled_disposable_move(**values)

    def setup_batch(self, maximum_actions=10):
        source = self.root / 'transient/Second'; source.mkdir()
        (source / 'payload').write_text('second disposable')
        session = RevisionedAuditSession(self.store)
        session.state['first_seen']['Second'] = '2024-01-01'
        session.checkpoint()
        snapshot, revision = self.store.load_with_revision()
        self.plan = collect_scheduled_plan(snapshot=snapshot, revision=revision,
            libraries=['Movies'], now=NOW, timer=lambda: 100, maximum_actions=maximum_actions,
            scan_library=lambda _: LibraryScan(True, [ScannedTitle(name, 'Waiting', 7, {})
                for name in ('Movie', 'Second')]))
        self.initial = snapshot

    def execute_batch(self, **kwargs):
        values = dict(root=self.root, database=self.database, plan=self.plan,
            title_folders={move.media_key: move.media_key for move in self.plan.moves},
            fetch_protection=lambda _: self.protection(), clock=lambda: NOW, timer=lambda: 101)
        values.update(kwargs)
        return execute_scheduled_disposable_batch(**values)

    def test_batch_two_moves_chain_revisions_and_never_replay(self):
        self.setup_batch()
        result = self.execute_batch()
        self.assertEqual(result['status'], 'disposable_batch_complete')
        self.assertEqual(len(result['completed']), 2)
        self.assertEqual(result['final_revision'], self.plan.revision + 6)
        self.assertEqual([item['revision'] for item in result['completed']],
                         [self.plan.revision + 3, self.plan.revision + 6])
        self.assertNotEqual(result['completed'][0]['operation_id'], result['completed'][1]['operation_id'])
        self.assertTrue((self.root / 'holding/Second/payload').exists())
        snapshot = self.store.load_with_revision()
        self.assertEqual(self.execute_batch()['status'], 'stopped')
        self.assertEqual(self.store.load_with_revision(), snapshot)

    def test_batch_second_title_saved_stops_without_undoing_completed_move(self):
        self.setup_batch()
        result = self.execute_batch(fetch_protection=lambda move:
            self.protection(keep=True) if move.media_key == 'Second' else self.protection())
        self.assertEqual(result['status'], 'stopped')
        self.assertEqual(len(result['completed']), 1)
        self.assertEqual(result['stopped_index'], 1)
        self.assertTrue(self.destination.exists())
        self.assertTrue((self.root / 'transient/Second').exists())
        self.assertNotIn(INTENTS_KEY, self.store.load_with_revision()[0])

    def test_batch_second_intent_failure_retains_first_completion_and_pending_second(self):
        self.setup_batch()
        result = self.execute_batch(fault_at=(1, 'after_intent'))
        self.assertEqual(result['status'], 'stopped')
        self.assertEqual(len(result['completed']), 1)
        snapshot, _ = self.store.load_with_revision()
        self.assertEqual(snapshot[INTENTS_KEY]['details']['media_key'], 'Second')
        self.assertEqual(snapshot['queued']['Movie'], NOW.isoformat())
        self.assertIn('Second', snapshot['first_seen'])
        self.assertTrue((self.root / 'transient/Second').exists())

    def test_batch_second_post_rename_failure_never_clears_or_replays(self):
        self.setup_batch()
        result = self.execute_batch(fault_at=(1, 'after_rename'))
        self.assertEqual(result['status'], 'stopped')
        snapshot = self.store.load_with_revision()
        self.assertIn(INTENTS_KEY, snapshot[0])
        self.assertIn('Second', snapshot[0]['first_seen'])
        self.assertTrue((self.root / 'holding/Second').exists())
        self.assertEqual(self.execute_batch()['status'], 'stopped')
        self.assertEqual(self.store.load_with_revision(), snapshot)

    def test_batch_action_cap_leaves_unplanned_source_untouched(self):
        self.setup_batch(maximum_actions=1)
        result = self.execute_batch()
        self.assertEqual(result['status'], 'disposable_batch_complete')
        self.assertEqual(result['capped_moves'], 1)
        self.assertEqual(len(result['completed']), 1)
        self.assertTrue((self.root / 'transient/Second').exists())

    def test_batch_competing_runner_cannot_enter_while_first_is_refreshing(self):
        self.setup_batch()
        def refresh(move):
            with self.assertRaisesRegex(RuntimeError, 'runner is active'):
                self.execute_batch()
            return self.protection()
        self.assertEqual(self.execute_batch(fetch_protection=refresh)['status'], 'disposable_batch_complete')

    def test_batch_unexpected_writer_after_completion_stops_revision_chain(self):
        self.setup_batch()
        import app.sqlite_scheduled_disposable_batch as batch
        original = batch._execute_scheduled_move_locked
        def interfere(**kwargs):
            result = original(**kwargs)
            session = RevisionedAuditSession(self.store)
            session.state['other_writer'] = {'changed': True}
            session.checkpoint()
            return result
        with patch.object(batch, '_execute_scheduled_move_locked', side_effect=interfere):
            result = self.execute_batch()
        self.assertEqual(result['status'], 'stopped')
        self.assertEqual(result['reason'], 'post_move_revision_or_state_changed')
        self.assertTrue((self.root / 'transient/Second').exists())
        self.assertTrue(self.destination.exists())

    def test_batch_collector_refetch_sees_second_title_saved_after_scan(self):
        self.setup_batch()
        from app.sqlite_scheduled_jellyfin import scheduled_protection_provider
        requests = []
        def fetch(path, params):
            requests.append(path)
            if path == '/Users': return [{'Id': 'fixture-user'}]
            refresh_number = requests.count('/Users')
            items = []
            for name in ('Movie', 'Second'):
                items.append({'Id': name, 'Type': 'Movie',
                    'Path': '/fixture/transient/' + name + '/payload',
                    'Tags': ['keep-forever'] if name == 'Second' and refresh_number >= 2 else [],
                    'UserData': {'IsFavorite': False, 'Played': False, 'PlayCount': 0}})
            return {'TotalRecordCount': len(items), 'Items': items}
        provider = scheduled_protection_provider(fetch=fetch,
            bindings={name: (name, 'Movie') for name in ('Movie', 'Second')}, clock=lambda: NOW)
        report = self.execute_batch(fetch_protection=provider)
        self.assertEqual(report['status'], 'stopped')
        self.assertEqual(len(report['completed']), 1)
        self.assertEqual(requests.count('/Users'), 2)
        self.assertTrue((self.root / 'transient/Second').exists())
        self.assertNotIn(INTENTS_KEY, self.store.load_with_revision()[0])

    def test_configured_paths_are_read_only_observations(self):
        from app.sqlite_scheduled_paths import review_scheduled_paths
        roots = {name: str(self.root / folder) for name, folder in
                 [('Waiting', 'transient'), ('Holding', 'holding'), ('Keep', 'keep'), ('Removal', 'removal')]}
        before = self.store.load_with_revision()
        report = review_scheduled_paths(stage_roots=roots, source_stage='Waiting',
            destination_stage='Holding', title_folder='Movie')
        self.assertEqual(report['status'], 'observed_advisory')
        self.assertFalse(report['production_authorized'])
        self.assertFalse(report['external_writers_excluded'])
        self.assertEqual(self.store.load_with_revision(), before)
        self.assertTrue(self.source.exists()); self.assertFalse(self.destination.exists())

    def test_configured_paths_detect_parent_replacement(self):
        from app.sqlite_scheduled_paths import hold_scheduled_paths
        roots = {name: str(self.root / folder) for name, folder in
                 [('Waiting', 'transient'), ('Holding', 'holding'), ('Keep', 'keep'), ('Removal', 'removal')]}
        with self.assertRaisesRegex(RuntimeError, 'identity changed'):
            with hold_scheduled_paths(stage_roots=roots, source_stage='Waiting',
                    destination_stage='Holding', title_folder='Movie') as held:
                (self.root / 'holding').rename(self.root / 'old-holding')
                (self.root / 'holding').mkdir()
                held.assert_unchanged()

    def test_pending_review_after_crash_retains_bytes_and_denies_clearance(self):
        from app.sqlite_scheduled_pending_review import review_scheduled_pending
        with self.assertRaises(RuntimeError): self.execute(fault_at='after_rename')
        before = self.database.read_bytes()
        report = review_scheduled_pending(self.database)
        self.assertEqual(report['status'], 'operator_review_required')
        self.assertFalse(report['clearance_authorized']); self.assertFalse(report['replay_allowed'])
        self.assertEqual(self.database.read_bytes(), before)

    def run_slot(self, **kwargs):
        from app.sqlite_scheduled_disposable_run import run_disposable_scheduled_slot
        from app.sqlite_run_schedule import DailyRunSchedule
        slot = datetime(2024, 2, 1, 2, tzinfo=timezone.utc)
        values = dict(root=self.root, schedule=DailyRunSchedule('02:00', 'UTC'), scheduled_at=slot,
            now=slot, libraries=['Movies'], clock=lambda: NOW, timer=lambda: 101,
            scan_library=lambda _: LibraryScan(True, [ScannedTitle('Movie', 'Waiting', 7, {})]),
            title_folders={'Movie': 'Movie'}, fetch_protection=lambda _: self.protection())
        values.update(kwargs)
        return run_disposable_scheduled_slot(**values)

    def test_full_scheduled_slot_claim_scan_move_and_no_duplicate(self):
        report = self.run_slot()
        self.assertEqual(report['status'], 'disposable_batch_complete')
        self.assertTrue(self.destination.exists())
        snapshot = self.store.load_with_revision()
        with self.assertRaises(FileExistsError): self.run_slot()
        self.assertEqual(self.store.load_with_revision(), snapshot)

    def test_full_slot_later_library_failure_never_dispatches_first_move(self):
        def scan(library):
            if library == 'Movies': return LibraryScan(True, [ScannedTitle('Movie', 'Waiting', 7, {})])
            raise TimeoutError('synthetic incomplete second library')
        with self.assertRaises(TimeoutError): self.run_slot(libraries=['Movies', 'TV'], scan_library=scan)
        self.assertTrue(self.source.exists()); self.assertFalse(self.destination.exists())
        self.assertEqual(self.store.load_with_revision()[0], self.initial)
        with self.assertRaises(FileExistsError): self.run_slot()

    def test_full_slot_holds_lock_while_collecting(self):
        from app.sqlite_isolated_lifecycle_runner import isolated_runner_lock
        def scan(library):
            with self.assertRaisesRegex(RuntimeError, 'runner is active'):
                with isolated_runner_lock(self.root): pass
            return LibraryScan(True, [ScannedTitle('Movie', 'Waiting', 7, {})])
        self.assertEqual(self.run_slot(scan_library=scan)['status'], 'disposable_batch_complete')

    def test_configured_cross_mount_destination_is_blocked_without_changes(self):
        from app.sqlite_scheduled_paths import review_scheduled_paths
        with tempfile.TemporaryDirectory(prefix='scheduled-destination-', dir='/dev/shm') as elsewhere:
            roots = {name: str(self.root / folder) for name, folder in
                 [('Waiting', 'transient'), ('Holding', 'holding'), ('Keep', 'keep'), ('Removal', 'removal')]}
            roots['Holding'] = elsewhere
            report = review_scheduled_paths(stage_roots=roots, source_stage='Waiting',
                destination_stage='Holding', title_folder='Movie')
            self.assertEqual(report['status'], 'blocked')
            self.assertEqual(list(Path(elsewhere).iterdir()), [])
            self.assertTrue(self.source.exists())

    def test_real_rename_commits_clock_and_clears_intent(self):
        result = self.execute()
        snapshot, revision = self.store.load_with_revision()
        self.assertEqual(result['status'], 'disposable_reconciled')
        self.assertFalse(result['production_authorized'])
        self.assertFalse(self.source.exists())
        self.assertEqual((self.destination / 'payload').read_text(), 'disposable original')
        self.assertNotIn('Movie', snapshot['first_seen'])
        self.assertEqual(snapshot['queued']['Movie'], NOW.isoformat())
        self.assertNotIn(INTENTS_KEY, snapshot)
        self.assertEqual(revision, self.plan.revision + 3)

    def test_protected_during_scan_never_records_intent_or_moves(self):
        with self.assertRaisesRegex(RuntimeError, 'fresh_decision_changed'):
            self.execute(fetch_protection=lambda _: self.protection(protected=True, keep_all=True))
        snapshot, revision = self.store.load_with_revision()
        self.assertEqual(snapshot, self.initial)
        self.assertEqual(revision, self.plan.revision)
        self.assertTrue(self.source.exists()); self.assertFalse(self.destination.exists())

    def test_unavailable_protection_leaves_source_and_tracking(self):
        with self.assertRaises(RuntimeError):
            self.execute(fetch_protection=lambda _: ProtectionRead(False, None))
        self.assertEqual(self.store.load_with_revision()[0], self.initial)
        self.assertTrue(self.source.exists())

    def test_fault_after_intent_retains_source_and_pending_no_replay(self):
        with self.assertRaisesRegex(RuntimeError, 'after intent'):
            self.execute(fault_at='after_intent')
        snapshot, _ = self.store.load_with_revision()
        self.assertEqual(snapshot[INTENTS_KEY]['phase'], 'intent_recorded')
        with self.assertRaises(RuntimeError): self.execute()
        self.assertEqual(self.store.load_with_revision()[0], snapshot)
        self.assertTrue(self.source.exists()); self.assertFalse(self.destination.exists())

    def test_fault_after_rename_retains_old_clock_and_pending(self):
        with self.assertRaisesRegex(RuntimeError, 'after rename'):
            self.execute(fault_at='after_rename')
        snapshot, _ = self.store.load_with_revision()
        self.assertIn(INTENTS_KEY, snapshot)
        self.assertEqual(snapshot['first_seen'], self.initial['first_seen'])
        self.assertEqual(snapshot['queued'], {})
        self.assertEqual((self.destination / 'payload').read_text(), 'disposable original')
        with self.assertRaises(RuntimeError): self.execute()
        self.assertEqual(self.store.load_with_revision()[0], snapshot)

    def test_killed_worker_retains_intent_and_releases_only_cooperating_lock(self):
        code = """
import os,signal
from datetime import datetime
from pathlib import Path
from app.sqlite_operation_coordinator import SQLiteOperationCoordinator
from app.sqlite_scheduled_plan import LibraryScan,ScannedTitle,collect_scheduled_plan
from app.sqlite_scheduled_recheck import ProtectionRead
from app.sqlite_jellyfin_signal_contract import SIGNAL_FIELDS
from app.sqlite_scheduled_disposable_executor import execute_scheduled_disposable_move
from app.state_store import GuardedSQLiteStateStore
root=Path(ROOT)
state,revision=GuardedSQLiteStateStore(root/'state.db').load_with_revision()
now=datetime(2024,2,1)
plan=collect_scheduled_plan(snapshot=state,revision=revision,libraries=['Movies'],now=now,
    scan_library=lambda _:LibraryScan(True,[ScannedTitle('Movie','Waiting',7,{})]),timer=lambda:100)
original=SQLiteOperationCoordinator.begin_move_with_evidence
def die(self,*args,**kwargs):
    original(self,*args,**kwargs)
    os.kill(os.getpid(),signal.SIGKILL)
SQLiteOperationCoordinator.begin_move_with_evidence=die
execute_scheduled_disposable_move(root=root,database=root/'state.db',operation_id='killed-fixture',
    plan=plan,move=plan.moves[0],title_folder='Movie',clock=lambda:now,timer=lambda:101,
    fetch_protection=lambda _:ProtectionRead(True,{key:False for key in SIGNAL_FIELDS}))
""".replace('ROOT', repr(str(self.root)), 1)
        child = subprocess.run([sys.executable, '-B', '-c', code], capture_output=True, timeout=30)
        self.assertEqual(child.returncode, -signal.SIGKILL, child.stderr.decode())
        snapshot, _ = self.store.load_with_revision()
        self.assertEqual(snapshot[INTENTS_KEY]['id'], 'killed-fixture')
        self.assertEqual(snapshot[INTENTS_KEY]['phase'], 'intent_recorded')
        self.assertTrue(self.source.exists()); self.assertFalse(self.destination.exists())
        with self.assertRaises(RuntimeError): self.execute()
        self.assertEqual(self.store.load_with_revision()[0], snapshot)

    def test_existing_destination_is_never_overwritten(self):
        self.destination.mkdir(); (self.destination / 'other').write_text('preserve')
        with self.assertRaises(RuntimeError): self.execute()
        self.assertEqual((self.destination / 'other').read_text(), 'preserve')
        self.assertTrue(self.source.exists())
        self.assertEqual(self.store.load_with_revision()[0], self.initial)

    def test_destination_created_during_refresh_hits_atomic_no_replace(self):
        def refresh(_):
            self.destination.mkdir(); (self.destination / 'other').write_text('racing writer')
            return self.protection()
        with self.assertRaises(OSError) as raised: self.execute(fetch_protection=refresh)
        self.assertEqual(raised.exception.errno, errno.EEXIST)
        self.assertEqual((self.destination / 'other').read_text(), 'racing writer')
        self.assertTrue(self.source.exists())
        self.assertIn(INTENTS_KEY, self.store.load_with_revision()[0])

    def test_source_replaced_during_refresh_never_moves_replacement(self):
        def refresh(_):
            self.source.rename(self.root / 'transient/Original')
            self.source.mkdir(); (self.source / 'payload').write_text('replacement')
            return self.protection()
        with self.assertRaisesRegex(RuntimeError, 'Source changed'):
            self.execute(fetch_protection=refresh)
        self.assertFalse(self.destination.exists())
        self.assertEqual((self.source / 'payload').read_text(), 'replacement')
        self.assertEqual((self.root / 'transient/Original/payload').read_text(), 'disposable original')
        self.assertIn(INTENTS_KEY, self.store.load_with_revision()[0])

    def test_expired_after_intent_does_not_rename(self):
        ticks = iter([101, 101, 101, 101, 3700])
        with self.assertRaisesRegex(RuntimeError, 'expired after intent'):
            self.execute(timer=lambda: next(ticks))
        self.assertTrue(self.source.exists()); self.assertFalse(self.destination.exists())
        self.assertIn(INTENTS_KEY, self.store.load_with_revision()[0])

    def test_unsupported_rename_has_no_copy_or_overwrite_fallback(self):
        with patch('app.sqlite_disposable_lifecycle_flow.rename_directory_noreplace_at',
                   side_effect=RuntimeError('Atomic no-replace rename unsupported')):
            with self.assertRaisesRegex(RuntimeError, 'unsupported'): self.execute()
        self.assertTrue(self.source.exists()); self.assertFalse(self.destination.exists())
        self.assertIn(INTENTS_KEY, self.store.load_with_revision()[0])

    def test_sync_failure_after_rename_retains_pending_and_old_clock(self):
        original = os.fsync
        def fsync(fd):
            if self.destination.exists() and os.fstat(fd).st_ino in {
                    os.stat(self.source.parent).st_ino, os.stat(self.destination.parent).st_ino}:
                raise OSError(errno.EIO, 'injected directory sync failure')
            return original(fd)
        with patch('app.sqlite_disposable_lifecycle_flow.os.fsync', side_effect=fsync):
            with self.assertRaises(OSError): self.execute()
        snapshot, _ = self.store.load_with_revision()
        self.assertIn(INTENTS_KEY, snapshot)
        self.assertEqual(snapshot['first_seen'], self.initial['first_seen'])
        self.assertTrue(self.destination.exists())


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ScheduledMoveFixtureTests))
    if not result.wasSuccessful() or result.skipped:
        raise SystemExit(1)
    print(json.dumps({'status': 'scheduled_disposable_rename_verified', 'tests': result.testsRun,
        'fixture_only': True, 'production_activation': 'disabled', 'production_authorized': False}))
