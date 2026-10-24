"""Standard-library acceptance tests using only new disposable Linux media."""
from datetime import datetime
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
