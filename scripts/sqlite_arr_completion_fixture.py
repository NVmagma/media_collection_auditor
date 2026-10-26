"""Private HTTP + pinned local identities + exact SQLite Arr completion CAS."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch
import unittest

from app.sqlite_arr_completion import complete_disposable_arr_request
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.state_store import GuardedSQLiteStateStore
from scripts.sqlite_arr_delivery_fixture import ArrDeliveryFixtureTests, Handler


class CompletionHandler(Handler):
    def reply(self, status, record):
        if self.server.hook is not None:
            self.server.hook(self.command, len(self.server.calls))
        super().reply(status, record)


class ArrCompletionFixtureTests(unittest.TestCase):
    def setUp(self):
        self.case = ArrDeliveryFixtureTests(); self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.case.server.RequestHandlerClass = CompletionHandler
        self.case.server.hook = None

    def prepare(self, service='radarr'):
        self.case.state['arr_sync_pending']['unrelated'] = {'stage': 'holding', 'root': '/unrelated', 'monitored': False, 'opaque': True}
        self.case.prepare(service)
        self.before = self.case.server.store.load_with_revision()

    def complete(self):
        c = self.case
        return complete_disposable_arr_request(root=c.root, operation_id='complete-one',
            media_key=c.key, title_folder='Title (2020)', details=c.details,
            source_path='/arr/holding/Title (2020)',
            base_url=f'http://127.0.0.1:{c.server.server_port}', token='synthetic-secret')

    def cannot_repeat(self):
        calls = list(self.case.server.calls)
        with self.assertRaises(RuntimeError): self.complete()
        self.assertEqual(self.case.server.calls, calls)

    def pending(self):
        state, _ = self.case.server.store.load_with_revision()
        self.assertIn(INTENTS_KEY, state)
        self.assertIn(self.case.key, state['arr_sync_pending'])
        self.assertEqual(state['keep_seen'], self.before[0]['keep_seen'])
        self.assertNotIn('synthetic-secret', json.dumps(state))
        self.cannot_repeat()
        return state

    def success(self, service):
        self.prepare(service)
        outcome = self.complete()
        state, revision = self.case.server.store.load_with_revision()
        expected = deepcopy(self.before[0]); expected['arr_sync_pending'].pop(self.case.key)
        self.assertEqual(state, expected)
        self.assertEqual(revision, self.before[1] + 3)
        self.assertEqual(outcome['revision'], revision)
        self.assertEqual(outcome['status'], 'disposable_arr_completion_verified')
        self.assertEqual(self.case.server.puts, 1)
        self.assertEqual(self.case.server.readbacks, 2)
        self.assertTrue(self.case.server.intent_before_put)
        self.cannot_repeat()

    def test_radarr_only_own_queue_and_intent_clear_atomically(self): self.success('radarr')
    def test_sonarr_keeps_seasons_clocks_and_unrelated_queue(self):
        self.success('sonarr')
        self.assertEqual(self.case.server.record['seasons'], [{'seasonNumber': 1, 'monitored': True}])

    def stage_completion(self, stage, clock):
        self.prepare()
        (self.case.root / 'keep' / 'Title (2020)').rename(self.case.root / stage / 'Title (2020)')
        state, revision = self.case.server.store.load_with_revision()
        state[clock][self.case.key] = state['keep_seen'].pop(self.case.key)
        self.case.details['root'] = '/arr/' + stage
        state['arr_sync_pending'][self.case.key].update(stage=stage, root='/arr/' + stage)
        self.case.server.store.save_if_revision(state, revision)
        self.before = self.case.server.store.load_with_revision()
        self.complete()
        expected = deepcopy(self.before[0]); expected['arr_sync_pending'].pop(self.case.key)
        state, revision = self.case.server.store.load_with_revision()
        self.assertEqual(state, expected)
        self.assertEqual(revision, self.before[1] + 3)
        self.assertEqual(self.case.server.record['path'], '/arr/' + stage + '/Title (2020)')
        self.cannot_repeat()

    def test_holding_completion_preserves_queued_clock(self): self.stage_completion('holding', 'queued')
    def test_removal_completion_preserves_removal_clock(self): self.stage_completion('removal', 'in_removal')

    def test_lost_put_acknowledgement_retains_intent_without_retry(self):
        self.prepare(); self.case.server.mode = 'lost-ack'
        with self.assertRaises(RuntimeError): self.complete()
        self.assertEqual(self.case.server.puts, 1)
        self.assertEqual(self.case.server.readbacks, 0)
        self.pending()

    def test_second_readback_mismatch_never_clears(self):
        self.prepare(); self.case.server.mode = 'second-mismatch'
        with self.assertRaises(RuntimeError): self.complete()
        self.pending()

    def alter_during_readback(self, action):
        def hook(method, count):
            if method == 'GET' and count == 3: action()
        self.case.server.hook = hook
        with self.assertRaises(RuntimeError): self.complete()
        self.assertEqual(self.case.server.readbacks, 1)
        self.pending()

    def test_title_replacement_during_readback_is_not_adopted(self):
        self.prepare(); title = self.case.root / 'keep' / 'Title (2020)'
        def action():
            title.rename(self.case.root / 'original-title'); title.mkdir()
        self.alter_during_readback(action)

    def test_stage_parent_replacement_during_readback_blocks(self):
        self.prepare(); parent = self.case.root / 'keep'
        def action():
            parent.rename(self.case.root / 'original-keep')
            parent.mkdir(); (parent / 'Title (2020)').mkdir()
        self.alter_during_readback(action)

    def test_identical_database_replacement_is_not_adopted(self):
        self.prepare()
        def action():
            original = self.case.database
            saved = original.with_name('original.db')
            original.rename(saved); original.write_bytes(saved.read_bytes())
        self.alter_during_readback(action)

    def test_concurrent_checkpoint_during_readback_blocks_clearance(self):
        self.prepare()
        def action():
            state, revision = self.case.server.store.load_with_revision()
            state['unknown']['external-change'] = True
            self.case.server.store.save_if_revision(state, revision)
        self.alter_during_readback(action)

    def test_queue_mutation_during_readback_blocks_clearance(self):
        self.prepare()
        def action():
            state, revision = self.case.server.store.load_with_revision()
            state['arr_sync_pending'][self.case.key]['monitored'] = True
            self.case.server.store.save_if_revision(state, revision)
        self.alter_during_readback(action)

    def test_final_sql_failure_preserves_applied_intent_and_queue(self):
        self.prepare(); original = GuardedSQLiteStateStore.save_if_revision
        def save(store, state, revision):
            if INTENTS_KEY not in state: raise RuntimeError('injected final SQL failure')
            return original(store, state, revision)
        with patch.object(GuardedSQLiteStateStore, 'save_if_revision', save):
            with self.assertRaises(RuntimeError): self.complete()
        self.assertEqual(self.pending()[INTENTS_KEY]['phase'], 'applied_pending_reconciliation')

    def test_lost_final_commit_ack_has_atomic_state_and_no_replay(self):
        self.prepare(); original = GuardedSQLiteStateStore.save_if_revision
        def save(store, state, revision):
            result = original(store, state, revision)
            if INTENTS_KEY not in state: raise RuntimeError('injected lost final acknowledgement')
            return result
        with patch.object(GuardedSQLiteStateStore, 'save_if_revision', save):
            with self.assertRaises(RuntimeError): self.complete()
        state, revision = self.case.server.store.load_with_revision()
        expected = deepcopy(self.before[0]); expected['arr_sync_pending'].pop(self.case.key)
        self.assertEqual(state, expected)
        self.assertEqual(revision, self.before[1] + 3)
        self.cannot_repeat()

    def test_existing_intent_blocks_before_http(self):
        self.prepare()
        state, revision = self.case.server.store.load_with_revision()
        state[INTENTS_KEY] = {'id': 'old-attempt', 'kind': 'arr_sync', 'phase': 'intent_recorded',
                             'details': dict(self.case.details)}
        self.case.server.store.save_if_revision(state, revision)
        self.cannot_repeat()
        self.assertEqual(self.case.server.calls, [])


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ArrCompletionFixtureTests))
    if not result.wasSuccessful() or result.testsRun != 14 or result.skipped: raise SystemExit(1)
    print(json.dumps({'status': 'known_outcome_arr_completion_verified', 'tests': result.testsRun,
        'fixture_only': True, 'production_authorized': False, 'production_activation': 'disabled'}))
