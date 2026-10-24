"""Real SQLite reconciliation rollback/visibility/crash tests; disposable only."""
from copy import deepcopy
import json
import os
import signal
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch

from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_audit_session import RevisionedAuditSession
from scripts.sqlite_scheduled_move_fixture import ScheduledMoveFixtureTests, NOW

REQUEST = {'service': 'radarr', 'title_id': 42, 'root': '/arr/holding', 'monitored': True}


@unittest.skipUnless(sys.platform == 'linux', 'Real scheduled rename acceptance requires Linux')
class ScheduledAtomicFixtureTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ScheduledMoveFixtureTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store = self.fixture.store; self.database = self.fixture.database
        session = RevisionedAuditSession(self.store)
        session.state['custom_tracking'] = {'nested': ['preserve', 7]}
        session.state['arr_sync_pending']['unrelated'] = {'stage': 'keep', 'root': '/arr/old', 'monitored': False}
        session.checkpoint()
        from app.sqlite_scheduled_plan import collect_scheduled_plan, LibraryScan, ScannedTitle
        snapshot, revision = self.store.load_with_revision()
        self.fixture.initial = snapshot
        self.fixture.plan = collect_scheduled_plan(snapshot=snapshot, revision=revision,
            libraries=['Movies'], now=NOW, timer=lambda: 100,
            scan_library=lambda _: LibraryScan(True, [ScannedTitle('Movie', 'Waiting', 7, {})]))
        self.base = revision

    def execute(self):
        return self.fixture.execute(arr_sync_request=REQUEST)

    def assert_preserved(self, state):
        self.assertEqual(state['custom_tracking'], {'nested': ['preserve', 7]})
        self.assertEqual(state['arr_sync_pending']['unrelated'],
                         {'stage': 'keep', 'root': '/arr/old', 'monitored': False})

    def assert_old(self, state, revision):
        self.assertEqual(revision, self.base + 2)
        self.assertEqual(state['first_seen']['Movie'], '2024-01-01')
        self.assertNotIn('Movie', state['queued'])
        self.assertNotIn('Movie', state['arr_sync_pending'])
        self.assertEqual(state[INTENTS_KEY]['phase'], 'applied_pending_reconciliation')
        self.assert_preserved(state)

    def assert_new(self, state, revision):
        self.assertEqual(revision, self.base + 3)
        self.assertNotIn('Movie', state['first_seen'])
        self.assertEqual(state['queued']['Movie'], NOW.isoformat())
        self.assertEqual(state['arr_sync_pending']['Movie'], {'stage': 'holding', **REQUEST})
        self.assertNotIn(INTENTS_KEY, state)
        self.assert_preserved(state)

    def trigger(self, sql):
        connection = sqlite3.connect(self.database)
        try:
            connection.execute(sql); connection.commit()
        finally:
            connection.close()

    def test_queue_request_is_detached_before_refresh_callback(self):
        request = deepcopy(REQUEST)
        def refresh(move):
            request['root'] = '/arr/changed-after-binding'
            return self.fixture.protection()
        self.fixture.execute(arr_sync_request=request, fetch_protection=refresh)
        self.assert_new(*self.store.load_with_revision())

    def test_existing_queue_is_preserved_and_blocks_before_intent(self):
        from dataclasses import replace
        writer = RevisionedAuditSession(self.store)
        writer.state['arr_sync_pending']['Movie'] = {'stage': 'keep', 'root': '/arr/existing', 'monitored': False}
        writer.checkpoint()
        before = self.store.load_with_revision()
        self.fixture.plan = replace(self.fixture.plan, revision=before[1])
        with self.assertRaisesRegex(RuntimeError, 'Existing Arr queue entry'): self.execute()
        self.assertEqual(self.store.load_with_revision(), before)
        self.assertTrue(self.fixture.source.exists()); self.assertFalse(self.fixture.destination.exists())

    def test_two_successful_queue_entries_are_chained_once_each(self):
        self.fixture.setup_batch(); self.base = self.fixture.plan.revision
        second = {**REQUEST, 'title_id': 43}
        report = self.fixture.execute_batch(arr_sync_requests={'Movie': REQUEST, 'Second': second})
        self.assertEqual(report['status'], 'disposable_batch_complete')
        state, revision = self.store.load_with_revision()
        self.assertEqual(revision, self.base + 6)
        self.assertEqual(state['arr_sync_pending']['Movie'], {'stage': 'holding', **REQUEST})
        self.assertEqual(state['arr_sync_pending']['Second'], {'stage': 'holding', **second})
        self.assertEqual(state['queued']['Movie'], NOW.isoformat())
        self.assertEqual(state['queued']['Second'], NOW.isoformat())
        self.assertNotIn(INTENTS_KEY, state); self.assert_preserved(state)

    def test_scheduled_transition_matrix_commits_the_correct_clock_and_queue(self):
        from app.sqlite_lifecycle_checkpoint_plan import CLOCKS
        from app.sqlite_scheduled_plan import collect_scheduled_plan, LibraryScan, ScannedTitle
        transitions = [('Waiting', 'Holding', {}, 'Movie'),
                       ('Waiting', 'Keep', {'keep': True}, 'Movie'),
                       ('Holding', 'Removal', {}, 'Movie'),
                       ('Holding', 'Keep', {'favorite': True}, 'TV/Movie')]
        for index, (source, destination, flags, key) in enumerate(transitions):
            with self.subTest(source=source, destination=destination, media_key=key):
                if index: self.setUp()  # A fresh disposable tree for each transition.
                source_folder = 'transient' if source == 'Waiting' else 'holding'
                if source_folder != 'transient':
                    self.fixture.source.rename(self.fixture.root / source_folder / 'Movie')
                session = RevisionedAuditSession(self.store)
                session.state['first_seen'].pop('Movie')
                session.state[CLOCKS[source]][key] = '2024-01-01'
                session.checkpoint()
                snapshot, revision = self.store.load_with_revision()
                self.fixture.plan = collect_scheduled_plan(snapshot=snapshot, revision=revision,
                    libraries=['TV' if key.startswith('TV/') else 'Movies'], now=NOW, timer=lambda: 100,
                    scan_library=lambda _: LibraryScan(True, [ScannedTitle(key, source, 7, flags)]))
                request = {**REQUEST, 'service': 'sonarr' if key.startswith('TV/') else 'radarr',
                           'root': '/arr/' + destination.lower()}
                report = self.fixture.execute(arr_sync_request=request,
                    fetch_protection=lambda _: self.fixture.protection(**flags))
                self.assertEqual(report['status'], 'disposable_reconciled')
                state, after = self.store.load_with_revision()
                self.assertEqual(after, revision + 3)
                self.assertNotIn(key, state[CLOCKS[source]])
                self.assertEqual(state[CLOCKS[destination]][key], NOW.isoformat())
                self.assertEqual(state['arr_sync_pending'][key], {'stage': destination.lower(), **request})
                self.assertNotIn(INTENTS_KEY, state); self.assert_preserved(state)

    def test_success_clock_queue_and_intent_are_one_revision(self):
        self.assertEqual(self.execute()['status'], 'disposable_reconciled')
        self.assert_new(*self.store.load_with_revision())

    def test_real_sql_failure_in_clock_insert_rolls_back_entire_snapshot(self):
        self.trigger("CREATE TRIGGER fail_clock BEFORE INSERT ON state_entries "
            "WHEN NEW.section='queued' AND NEW.media_key='Movie' "
            "BEGIN SELECT RAISE(ABORT,'injected clock insert failure'); END")
        with self.assertRaises(RuntimeError): self.execute()
        self.assert_old(*self.store.load_with_revision())
        self.assertTrue(self.fixture.destination.exists())

    def test_real_sql_failure_in_arr_insert_rolls_back_clock_and_clearance(self):
        self.trigger("CREATE TRIGGER fail_queue BEFORE INSERT ON state_entries "
            "WHEN NEW.section='arr_sync_pending' AND NEW.media_key='Movie' "
            "BEGIN SELECT RAISE(ABORT,'injected queue insert failure'); END")
        with self.assertRaises(RuntimeError): self.execute()
        self.assert_old(*self.store.load_with_revision())

    def test_real_sql_failure_deleting_intent_rolls_back_clock_changes(self):
        self.trigger("CREATE TRIGGER fail_clear BEFORE DELETE ON extra_state "
            "WHEN OLD.key='sqlite_pending_operations' AND OLD.value_json LIKE '%applied_pending_reconciliation%' "
            "BEGIN SELECT RAISE(ABORT,'injected intent delete failure'); END")
        with self.assertRaises(RuntimeError): self.execute()
        self.assert_old(*self.store.load_with_revision())

    def test_real_sql_failure_in_revision_update_rolls_back_all_fields(self):
        self.trigger("CREATE TRIGGER fail_revision BEFORE UPDATE ON metadata "
            "WHEN OLD.key='state_revision' AND NEW.value='" + str(self.base + 3) + "' "
            "BEGIN SELECT RAISE(ABORT,'injected revision failure'); END")
        with self.assertRaises(RuntimeError): self.execute()
        self.assert_old(*self.store.load_with_revision())

    def connect_hook(self, callback):
        original = sqlite3.connect
        case = self
        class Connection:
            def __init__(self, connection): self.raw = connection
            def __getattr__(self, name): return getattr(self.raw, name)
            def commit(self):
                revision = self.raw.execute("SELECT value FROM metadata WHERE key='state_revision'").fetchone()
                if revision == (str(case.base + 3),):
                    return callback(self.raw)
                return self.raw.commit()
        def connect(*args, **kwargs):
            connection = original(*args, **kwargs)
            return Connection(connection) if args and 'mode=rw' in str(args[0]) else connection
        return patch('app.sqlite_store.sqlite3.connect', side_effect=connect)

    def test_independent_reader_sees_old_then_new_never_partial_transaction(self):
        observations = []
        def commit(connection):
            self.assert_old(*self.store.load_with_revision()); observations.append('old')
            connection.commit()
            self.assert_new(*self.store.load_with_revision()); observations.append('new')
        with self.connect_hook(commit): self.execute()
        self.assertEqual(observations, ['old', 'new'])

    def test_exception_before_commit_retains_complete_old_state(self):
        def fail(connection): raise OSError('injected before commit')
        with self.connect_hook(fail):
            with self.assertRaises(RuntimeError): self.execute()
        self.assert_old(*self.store.load_with_revision())

    def test_exception_after_commit_is_complete_new_state_and_no_replay(self):
        def fail(connection):
            connection.commit(); raise OSError('injected acknowledgement failure')
        with self.connect_hook(fail):
            with self.assertRaises(RuntimeError): self.execute()
        self.assert_new(*self.store.load_with_revision())
        before = self.store.load_with_revision()
        with self.assertRaises(RuntimeError): self.execute()
        self.assertEqual(self.store.load_with_revision(), before)

    def test_intervening_revision_cannot_be_adopted_by_final_reconciler(self):
        import app.sqlite_disposable_lifecycle_flow as flow
        original = flow.reconcile_witnessed_disposable_rename
        def intervene(**kwargs):
            writer = RevisionedAuditSession(self.store)
            writer.state['external_update'] = {'preserve': True}; writer.checkpoint()
            return original(**kwargs)
        with patch.object(flow, 'reconcile_witnessed_disposable_rename', side_effect=intervene):
            with self.assertRaisesRegex(RuntimeError, 'state changed'): self.execute()
        state, revision = self.store.load_with_revision()
        self.assertEqual(revision, self.base + 3)
        self.assertIn(INTENTS_KEY, state); self.assertIn('Movie', state['first_seen'])
        self.assertNotIn('Movie', state['arr_sync_pending'])
        self.assertEqual(state['external_update'], {'preserve': True})

    def test_same_revision_changed_snapshot_cannot_clear_intent(self):
        import app.sqlite_disposable_lifecycle_flow as flow
        original = flow.reconcile_witnessed_disposable_rename
        def intervene(**kwargs):
            connection = sqlite3.connect(self.database)
            try:
                connection.execute("UPDATE extra_state SET value_json=? WHERE key='custom_tracking'",
                                   (json.dumps({'changed_without_revision': True}),))
                connection.commit()
            finally: connection.close()
            return original(**kwargs)
        with patch.object(flow, 'reconcile_witnessed_disposable_rename', side_effect=intervene):
            with self.assertRaisesRegex(RuntimeError, 'state changed'): self.execute()
        state, revision = self.store.load_with_revision()
        self.assertEqual(revision, self.base + 2)
        self.assertIn(INTENTS_KEY, state); self.assertIn('Movie', state['first_seen'])
        self.assertEqual(state['custom_tracking'], {'changed_without_revision': True})

    def test_cas_race_during_final_save_retains_competing_writer(self):
        from app.state_store import GuardedSQLiteStateStore
        original = GuardedSQLiteStateStore.save_if_revision
        def race(store, state, revision):
            if INTENTS_KEY not in state and 'Movie' in state['queued']:
                other, current = store.load_with_revision()
                other['external_update'] = {'preserve': True}
                original(store, other, current)
            return original(store, state, revision)
        with patch.object(GuardedSQLiteStateStore, 'save_if_revision', race):
            with self.assertRaises(RuntimeError): self.execute()
        state, revision = self.store.load_with_revision()
        self.assertEqual(revision, self.base + 3)
        self.assertIn(INTENTS_KEY, state); self.assertIn('Movie', state['first_seen'])
        self.assertNotIn('Movie', state['arr_sync_pending'])
        self.assertEqual(state['external_update'], {'preserve': True})

    def test_batch_second_reconcile_failure_preserves_first_atomic_result(self):
        self.fixture.setup_batch(); self.base = self.fixture.plan.revision
        self.trigger("CREATE TRIGGER fail_second BEFORE INSERT ON state_entries "
            "WHEN NEW.section='queued' AND NEW.media_key='Second' "
            "BEGIN SELECT RAISE(ABORT,'injected second clock failure'); END")
        second = {**REQUEST, 'title_id': 43}
        result = self.fixture.execute_batch(arr_sync_requests={'Movie': REQUEST, 'Second': second})
        self.assertEqual(result['status'], 'stopped'); self.assertEqual(len(result['completed']), 1)
        state, revision = self.store.load_with_revision()
        self.assertEqual(revision, self.base + 5)
        self.assertEqual(state['queued']['Movie'], NOW.isoformat())
        self.assertEqual(state['arr_sync_pending']['Movie'], {'stage': 'holding', **REQUEST})
        self.assertIn('Second', state['first_seen']); self.assertNotIn('Second', state['queued'])
        self.assertNotIn('Second', state['arr_sync_pending'])
        self.assertEqual(state[INTENTS_KEY]['details']['media_key'], 'Second')
        self.assert_preserved(state)

    def test_batch_acknowledgement_failure_stops_before_next_title(self):
        self.fixture.setup_batch(); self.base = self.fixture.plan.revision
        def fail(connection):
            connection.commit(); raise OSError('injected acknowledgement failure')
        with self.connect_hook(fail):
            result = self.fixture.execute_batch(arr_sync_requests={'Movie': REQUEST})
        self.assertEqual(result['status'], 'stopped'); self.assertEqual(result['stopped_index'], 0)
        self.assertEqual(result['completed'], ())
        self.assert_new(*self.store.load_with_revision())
        self.assertTrue((self.fixture.root / 'transient/Second').exists())

    def kill_at_commit(self, when):
        code = r'''
import os,signal,sqlite3
from pathlib import Path
from datetime import datetime,timezone
from app.sqlite_scheduled_disposable_run import run_disposable_scheduled_slot
from app.sqlite_run_schedule import DailyRunSchedule
from app.sqlite_scheduled_plan import LibraryScan,ScannedTitle
from app.sqlite_scheduled_recheck import ProtectionRead
from app.sqlite_jellyfin_signal_contract import SIGNAL_FIELDS
from app.state_store import GuardedSQLiteStateStore
root=Path(ROOT)
_,base=GuardedSQLiteStateStore(root/'state.db').load_with_revision()
original=sqlite3.connect
class Connection:
    def __init__(self,raw): self.raw=raw
    def __getattr__(self,name): return getattr(self.raw,name)
    def commit(self):
        revision=self.raw.execute("SELECT value FROM metadata WHERE key='state_revision'").fetchone()
        if revision==(str(base+3),):
            if WHEN=='after': self.raw.commit()
            os.kill(os.getpid(),signal.SIGKILL)
        return self.raw.commit()
def connect(*args,**kwargs):
    raw=original(*args,**kwargs)
    return Connection(raw) if args and 'mode=rw' in str(args[0]) else raw
sqlite3.connect=connect
slot=datetime(2024,2,1,2,tzinfo=timezone.utc)
run_disposable_scheduled_slot(root=root,schedule=DailyRunSchedule('02:00','UTC'),scheduled_at=slot,now=slot,
    libraries=['Movies'],clock=lambda:datetime(2024,2,1),timer=lambda:101,
    scan_library=lambda _:LibraryScan(True,[ScannedTitle('Movie','Waiting',7,{})]),
    title_folders={'Movie':'Movie'},fetch_protection=lambda _:ProtectionRead(True,{k:False for k in SIGNAL_FIELDS}),
    arr_sync_requests={'Movie':REQUEST})
'''.replace('ROOT', repr(str(self.fixture.root)), 1).replace('WHEN', repr(when), 1).replace('REQUEST', repr(REQUEST), 1)
        child = subprocess.run([sys.executable, '-S', '-B', '-c', code], capture_output=True, timeout=30)
        self.assertEqual(child.returncode, -signal.SIGKILL, child.stderr.decode())
        # Only this new disposable DB is opened writable for SQLite's journal
        # recovery. This is not application replay or a production recovery API.
        connection = sqlite3.connect(self.database)
        try: connection.execute('SELECT count(*) FROM metadata').fetchone()
        finally: connection.close()
        with self.assertRaises(FileExistsError): self.fixture.run_slot()

    def test_sigkill_before_final_commit_recovers_complete_old_state(self):
        self.kill_at_commit('before')
        self.assert_old(*self.store.load_with_revision())
        self.assertTrue(self.fixture.destination.exists())

    def test_sigkill_after_final_commit_retains_complete_new_state(self):
        self.kill_at_commit('after')
        self.assert_new(*self.store.load_with_revision())


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ScheduledAtomicFixtureTests))
    if not result.wasSuccessful() or result.skipped: raise SystemExit(1)
    print(json.dumps({'status': 'scheduled_atomic_reconciliation_verified', 'tests': result.testsRun,
        'fixture_only': True, 'production_activation': 'disabled', 'production_authorized': False}))
