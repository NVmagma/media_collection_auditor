"""Actual Linux routed movie/TV moves in a new marked lab, never production."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import signal
import sys
import unittest
from unittest.mock import patch

from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_scheduled_clock_checkpoint import prepare_checkpointed_disposable_worker
from app.sqlite_scheduled_routed_batch import execute_disposable_routed_batch
from app.sqlite_scheduled_recheck import ProtectionRead
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_audit_session import RevisionedAuditSession
from app.state_store import GuardedSQLiteStateStore
from scripts.sqlite_scheduled_worker_fixture import ScheduledWorkerFixtureTests
import app.sqlite_scheduled_routed_batch as module

NOW = datetime(2026, 10, 24)


@unittest.skipUnless(sys.platform == 'linux', 'Real no-replace rename requires Linux')
class ScheduledRoutedFixtureTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ScheduledWorkerFixtureTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        (self.root / '.sqlite_disposable_rehearsal').write_text('DISPOSABLE ONLY\n')
        for library in self.fixture.libraries:
            payload = Path(library['transient']) / 'Same (2020)' / 'payload'
            payload.write_bytes(b'disposable original')
            stamp = datetime(2026, 1, 1).timestamp(); os.utime(payload, (stamp, stamp))
        snapshot = deepcopy(self.fixture.snapshot)
        snapshot['custom'] = {'preserve': 'unknown'}
        snapshot['arr_sync_pending']['other'] = {'stage': 'keep', 'root': '/arr/other'}
        write_offline_snapshot(snapshot, self.root / 'state.db')
        self.store = GuardedSQLiteStateStore(self.root / 'state.db')
        self.config = self.fixture.config()
        self.prepared = self.prepare()
        self.initial, self.revision = self.store.load_with_revision()
        self.calls = []

    def signals(self, **flags):
        values = {field: False for field in ('played', 'favorite', 'disliked', 'keep', 'keep_all', 'protected')}
        values.update(flags)
        return values

    def prepare(self):
        return prepare_checkpointed_disposable_worker(root=self.root, config=self.config,
            fetch_signals=lambda _: self.signals(), clock=lambda: NOW).preparation

    def protection(self, move):
        self.calls.append(move.media_key)
        return ProtectionRead(True, self.signals())

    def execute(self, **kwargs):
        return execute_disposable_routed_batch(root=self.root, config=kwargs.pop('config', self.config),
            preparation=self.prepared, fetch_protection=kwargs.pop('fetch_protection', self.protection),
            clock=kwargs.pop('clock', lambda: NOW), **kwargs)

    def path(self, index, stage):
        return Path(self.fixture.libraries[index][stage]) / 'Same (2020)'

    def test_identical_movie_tv_names_route_separately_and_share_one_revision_chain(self):
        result = self.execute()
        self.assertEqual(result['status'], 'disposable_routed_batch_complete')
        self.assertEqual([row['media_key'] for row in result['completed']], ['Same (2020)', 'TV/Same (2020)'])
        state, revision = self.store.load_with_revision()
        self.assertEqual(revision, self.revision + 6)
        self.assertEqual(state['first_seen'], {})
        self.assertEqual(set(state['queued']), {'Same (2020)', 'TV/Same (2020)'})
        self.assertEqual(state['custom'], self.initial['custom'])
        self.assertEqual(state['arr_sync_pending'], self.initial['arr_sync_pending'])
        self.assertNotIn(INTENTS_KEY, state)
        for index in (0, 1):
            self.assertFalse(self.path(index, 'transient').exists())
            self.assertTrue(self.path(index, 'holding').is_dir())
            self.assertEqual((self.path(index, 'holding') / 'payload').read_bytes(), b'disposable original')

    def test_global_action_cap_does_not_restart_for_tv(self):
        self.config = self.fixture.config(cap=1); self.prepared = self.prepare()
        result = self.execute()
        self.assertEqual(len(result['completed']), 1)
        self.assertEqual(result['capped_moves'], 1)
        self.assertTrue(self.path(0, 'holding').is_dir())
        self.assertTrue(self.path(1, 'transient').is_dir())
        self.assertEqual(self.calls, ['Same (2020)'])

    def test_changed_fresh_tags_stop_before_any_intent_or_rename(self):
        result = self.execute(fetch_protection=lambda _: ProtectionRead(True, self.signals(keep=True)))
        self.assertEqual(result['status'], 'stopped')
        self.assertEqual(result['completed'], ())
        self.assertEqual(self.store.load_with_revision(), (self.initial, self.revision))
        self.assertTrue(self.path(0, 'transient').is_dir())

    def test_second_title_failure_preserves_first_completion_and_keeps_second_source(self):
        def protection(move):
            return ProtectionRead(move.library != 'TV', self.signals() if move.library != 'TV' else None)
        result = self.execute(fetch_protection=protection)
        self.assertEqual(result['status'], 'stopped')
        self.assertEqual(len(result['completed']), 1)
        state, revision = self.store.load_with_revision()
        self.assertEqual(revision, self.revision + 3)
        self.assertIn('Same (2020)', state['queued'])
        self.assertIn('TV/Same (2020)', state['first_seen'])
        self.assertTrue(self.path(1, 'transient').is_dir())
        self.assertNotIn(INTENTS_KEY, state)

    def test_occupied_destination_is_never_overwritten(self):
        destination = self.path(0, 'holding'); destination.mkdir()
        (destination / 'preserve').write_bytes(b'existing')
        result = self.execute()
        self.assertEqual(result['status'], 'stopped')
        self.assertEqual((destination / 'preserve').read_bytes(), b'existing')
        self.assertTrue(self.path(0, 'transient').is_dir())
        self.assertEqual(self.store.load_with_revision(), (self.initial, self.revision))

    def test_source_replacement_is_not_adopted(self):
        source = self.path(0, 'transient'); source.rename(source.with_name('original')); source.mkdir()
        result = self.execute()
        self.assertEqual(result['status'], 'stopped')
        self.assertEqual(self.store.load_with_revision(), (self.initial, self.revision))
        self.assertTrue(source.with_name('original').is_dir())

    def test_configured_root_replacement_blocks_before_intent(self):
        stage = Path(self.fixture.libraries[1]['keep'])
        stage.rename(stage.with_name('old')); stage.mkdir()
        result = self.execute()
        self.assertEqual(result['status'], 'stopped')
        self.assertEqual(self.store.load_with_revision(), (self.initial, self.revision))

    def test_policy_change_cannot_reuse_an_old_preparation(self):
        changed = replace(self.config, favorites_trigger_keep=False)
        with self.assertRaises(ValueError): self.execute(config=changed)
        self.assertEqual(self.store.load_with_revision(), (self.initial, self.revision))

    def test_failure_after_actual_rename_retains_intent_and_blocks_replay(self):
        original = module.rename_directory_noreplace_at
        def rename(*args):
            original(*args)
            raise RuntimeError('fixture acknowledgement loss')
        with patch.object(module, 'rename_directory_noreplace_at', rename): result = self.execute()
        self.assertEqual(result['status'], 'stopped')
        state, revision = self.store.load_with_revision()
        self.assertEqual(revision, self.revision + 1)
        self.assertEqual(state[INTENTS_KEY]['phase'], 'intent_recorded')
        self.assertTrue(self.path(0, 'holding').is_dir())
        with patch.object(module, 'rename_directory_noreplace_at', side_effect=AssertionError('replay')):
            again = self.execute()
        self.assertEqual(again['status'], 'stopped')
        self.assertEqual(self.store.load_with_revision(), (state, revision))

    def test_unsupported_atomic_rename_has_no_copy_fallback(self):
        with patch.object(module, 'rename_directory_noreplace_at', side_effect=RuntimeError('unsupported')):
            result = self.execute()
        self.assertEqual(result['status'], 'stopped')
        state, revision = self.store.load_with_revision()
        self.assertEqual(revision, self.revision + 1)
        self.assertIn(INTENTS_KEY, state)
        self.assertTrue(self.path(0, 'transient').is_dir())
        self.assertFalse(self.path(0, 'holding').exists())

    def test_movie_and_sonarr_queue_entries_commit_with_their_own_clocks(self):
        requests = {key: {'service': service, 'title_id': number, 'root': '/arr/' + service, 'monitored': False}
                    for key, service, number in [('Same (2020)', 'radarr', 1), ('TV/Same (2020)', 'sonarr', 2)]}
        result = self.execute(arr_sync_requests=requests)
        self.assertEqual(result['status'], 'disposable_routed_batch_complete')
        state, _ = self.store.load_with_revision()
        for key, request in requests.items():
            self.assertEqual(state['arr_sync_pending'][key], {'stage': 'holding', **request})
            self.assertIn(key, state['queued'])
        self.assertEqual(state['arr_sync_pending']['other'], self.initial['arr_sync_pending']['other'])

    def test_final_sql_failure_retains_applied_intent_and_old_clocks(self):
        with sqlite3.connect(self.root / 'state.db') as connection:
            connection.execute("CREATE TRIGGER fail_clear BEFORE DELETE ON extra_state WHEN OLD.key='sqlite_pending_operations' BEGIN SELECT CASE WHEN json_extract(OLD.value_json,'$.phase')='applied_pending_reconciliation' THEN RAISE(ABORT,'fixture') END; END")
        result = self.execute()
        self.assertEqual(result['status'], 'stopped')
        state, revision = self.store.load_with_revision()
        self.assertEqual(revision, self.revision + 2)
        self.assertEqual(state['first_seen'], self.initial['first_seen'])
        self.assertEqual(state['queued'], {})
        self.assertEqual(state[INTENTS_KEY]['phase'], 'applied_pending_reconciliation')
        self.assertTrue(self.path(0, 'holding').is_dir())

    def test_stale_tracking_blocks_without_touching_sources(self):
        other = RevisionedAuditSession(self.store); other.state['custom']['writer'] = True; other.checkpoint()
        before = self.store.load_with_revision()
        self.assertEqual(self.execute()['status'], 'stopped')
        self.assertEqual(self.store.load_with_revision(), before)
        self.assertTrue(self.path(0, 'transient').is_dir())

    def test_empty_plan_never_clears_pending_discovery_changes(self):
        self.prepared = replace(self.prepared, clock_proposal=replace(self.prepared.clock_proposal,
            changes=(('Same (2020)', 'discovered', 'first_seen'),)))
        with self.assertRaises(ValueError): self.execute()
        self.assertEqual(self.store.load_with_revision(), (self.initial, self.revision))


    def test_waiting_holding_keep_removal_transition_matrix(self):
        for source, destination in [('Waiting', 'Holding'), ('Waiting', 'Keep'),
                                    ('Holding', 'Removal'), ('Holding', 'Keep')]:
            with self.subTest(source=source, destination=destination):
                probe = ScheduledRoutedFixtureTests(); probe.setUp()
                try:
                    if source == 'Holding':
                        session = RevisionedAuditSession(probe.store)
                        for index, key in [(0, 'Same (2020)'), (1, 'TV/Same (2020)')]:
                            probe.path(index, 'transient').rename(probe.path(index, 'holding'))
                            session.state['queued'][key] = session.state['first_seen'].pop(key)
                        session.checkpoint()
                    flags = probe.signals(keep=destination == 'Keep')
                    probe.prepared = prepare_checkpointed_disposable_worker(root=probe.root,
                        config=probe.config, fetch_signals=lambda _: flags, clock=lambda: NOW).preparation
                    result = probe.execute(fetch_protection=lambda _: ProtectionRead(True, flags))
                    self.assertEqual(result['status'], 'disposable_routed_batch_complete')
                    state, _ = probe.store.load_with_revision()
                    section = {'Holding': 'queued', 'Keep': 'keep_seen', 'Removal': 'in_removal'}[destination]
                    self.assertEqual(set(state[section]), {'Same (2020)', 'TV/Same (2020)'})
                    field = {'Holding': 'holding', 'Keep': 'keep', 'Removal': 'removal'}[destination]
                    for index in (0, 1):
                        self.assertEqual((probe.path(index, field) / 'payload').read_bytes(), b'disposable original')
                finally: probe.doCleanups()

    def test_new_tv_content_blocks_second_move_before_its_intent(self):
        self.fixture.libraries[1]['new_content_resets_clock'] = True
        self.config = self.fixture.config(); self.prepared = self.prepare()
        def protection(move):
            if move.library == 'TV':
                episode = self.path(1, 'transient') / 'new.mkv'; episode.write_bytes(b'new')
                at = datetime(2026, 10, 1).timestamp(); os.utime(episode, (at, at))
            return self.protection(move)
        result = self.execute(fetch_protection=protection)
        self.assertEqual(result['status'], 'stopped')
        self.assertEqual(len(result['completed']), 1)
        state, revision = self.store.load_with_revision()
        self.assertEqual(revision, self.revision + 3)
        self.assertNotIn(INTENTS_KEY, state)
        self.assertTrue(self.path(1, 'transient').is_dir())

    def test_parent_sync_failure_retains_intent_after_rename(self):
        with patch.object(module.os, 'fsync', side_effect=OSError('fixture parent sync')):
            result = self.execute()
        self.assertEqual(result['status'], 'stopped')
        state, revision = self.store.load_with_revision()
        self.assertEqual(revision, self.revision + 1)
        self.assertEqual(state[INTENTS_KEY]['phase'], 'intent_recorded')
        self.assertTrue(self.path(0, 'holding').is_dir())
        self.assertTrue(self.path(1, 'transient').is_dir())

    def test_lost_final_commit_acknowledgement_stops_before_tv_without_replay(self):
        original = GuardedSQLiteStateStore.save_if_revision
        def save(store, state, revision):
            original(store, state, revision)
            if INTENTS_KEY not in state and revision == self.revision + 2:
                raise RuntimeError('fixture final acknowledgement lost')
        with patch.object(GuardedSQLiteStateStore, 'save_if_revision', save): result = self.execute()
        self.assertEqual(result['status'], 'stopped')
        self.assertEqual(result['completed'], ())
        state, revision = self.store.load_with_revision()
        self.assertEqual(revision, self.revision + 3)
        self.assertNotIn(INTENTS_KEY, state)
        self.assertIn('Same (2020)', state['queued'])
        self.assertIn('TV/Same (2020)', state['first_seen'])
        self.assertTrue(self.path(1, 'transient').is_dir())
        self.assertEqual(self.execute()['status'], 'stopped')
        self.assertEqual(self.store.load_with_revision(), (state, revision))

    def test_protection_expiry_after_intent_never_renames(self):
        tick = [self.prepared.plan.created_tick + 0.01]
        original = module.SQLiteOperationCoordinator.begin_move_with_evidence
        def begin(coordinator, *args):
            original(coordinator, *args)
            tick[0] = self.prepared.plan.deadline_tick + 1
        with patch.object(module.SQLiteOperationCoordinator, 'begin_move_with_evidence', begin):
            result = self.execute(timer=lambda: tick[0])
        self.assertEqual(result['status'], 'stopped')
        state, revision = self.store.load_with_revision()
        self.assertEqual(revision, self.revision + 1)
        self.assertEqual(state[INTENTS_KEY]['phase'], 'intent_recorded')
        self.assertTrue(self.path(0, 'transient').is_dir())
        self.assertFalse(self.path(0, 'holding').exists())

    def test_same_revision_applied_mutation_cannot_clear_intent(self):
        original = module.SQLiteOperationCoordinator.mark_applied
        def applied(coordinator, *args):
            original(coordinator, *args)
            with sqlite3.connect(self.root / 'state.db') as connection:
                connection.execute("UPDATE extra_state SET value_json='{}' WHERE key='custom'")
        with patch.object(module.SQLiteOperationCoordinator, 'mark_applied', applied): result = self.execute()
        self.assertEqual(result['status'], 'stopped')
        state, revision = self.store.load_with_revision()
        self.assertEqual(revision, self.revision + 2)
        self.assertEqual(state['custom'], {})
        self.assertEqual(state[INTENTS_KEY]['phase'], 'applied_pending_reconciliation')
        self.assertEqual(state['first_seen'], self.initial['first_seen'])

    def test_actual_sigkill_after_rename_retains_intent_and_prevents_replay(self):
        script = r"""
import json,sys,os,signal
from datetime import datetime
from app.sqlite_scheduled_worker import configured_scheduled_worker
from app.sqlite_scheduled_clock_checkpoint import prepare_checkpointed_disposable_worker
from app.sqlite_scheduled_recheck import ProtectionRead
import app.sqlite_scheduled_routed_batch as routed
request=json.load(sys.stdin)
config=configured_scheduled_worker(libraries=request['libraries'],local_time='02:00',timezone_name='America/Los_Angeles',holding_days=7)
signals={field:False for field in ('played','favorite','disliked','keep','keep_all','protected')}
clock=lambda:datetime(2026,10,24)
prepared=prepare_checkpointed_disposable_worker(root=request['root'],config=config,fetch_signals=lambda _:signals,clock=clock).preparation
original=routed.rename_directory_noreplace_at
def rename(*args):
    original(*args)
    os.kill(os.getpid(),signal.SIGKILL)
routed.rename_directory_noreplace_at=rename
routed.execute_disposable_routed_batch(root=request['root'],config=config,preparation=prepared,fetch_protection=lambda _:ProtectionRead(True,signals),clock=clock)
"""
        child = subprocess.run([sys.executable, '-S', '-B', '-c', script],
            input=json.dumps({'root': str(self.root), 'libraries': self.fixture.libraries}).encode(),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        self.assertEqual(child.returncode, -signal.SIGKILL, child.stderr.decode())
        state, revision = self.store.load_with_revision()
        self.assertEqual(revision, self.revision + 1)
        self.assertEqual(state[INTENTS_KEY]['phase'], 'intent_recorded')
        self.assertEqual(state['first_seen'], self.initial['first_seen'])
        self.assertTrue(self.path(0, 'holding').is_dir())
        self.assertTrue(self.path(1, 'transient').is_dir())
        with patch.object(module, 'rename_directory_noreplace_at', side_effect=AssertionError('replay')):
            self.assertEqual(self.execute()['status'], 'stopped')
        self.assertEqual(self.store.load_with_revision(), (state, revision))


    def test_existing_candidate_arr_queue_blocks_even_without_new_queue_request(self):
        session = RevisionedAuditSession(self.store)
        session.state['arr_sync_pending']['Same (2020)'] = {'stage': 'keep', 'root': '/arr/original'}
        session.checkpoint(); self.prepared = self.prepare()
        before = self.store.load_with_revision()
        result = self.execute()
        self.assertEqual(result['status'], 'stopped')
        self.assertEqual(self.store.load_with_revision(), before)
        self.assertTrue(self.path(0, 'transient').is_dir())
        self.assertFalse(self.path(0, 'holding').exists())


def main():
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(
        ScheduledRoutedFixtureTests))
    if not result.wasSuccessful() or result.skipped or result.testsRun != 22: return 1
    print(json.dumps({'status': 'scheduled_routed_batch_verified', 'tests': result.testsRun,
        'fixture_only': True, 'production_activation': 'disabled', 'production_authorized': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
