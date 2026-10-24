"""Real SQLite clock checkpoints using only newly created disposable lab trees."""
from copy import deepcopy
from datetime import datetime
from dataclasses import replace
import json
import os
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_scheduled_clock_checkpoint import prepare_checkpointed_disposable_worker
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.state_store import GuardedSQLiteStateStore
from scripts.sqlite_scheduled_worker_fixture import ScheduledWorkerFixtureTests


class ScheduledClockCheckpointFixtureTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ScheduledWorkerFixtureTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        (self.root / '.sqlite_disposable_rehearsal').write_text('DISPOSABLE ONLY\n')
        self.database = self.root / 'state.db'
        snapshot = deepcopy(self.fixture.snapshot)
        snapshot['first_seen'].clear()
        snapshot['custom'] = {'preserve': [1, 2]}
        snapshot['arr_sync_pending']['unrelated'] = {'stage': 'keep', 'root': '/arr/keep'}
        write_offline_snapshot(snapshot, self.database)
        self.store = GuardedSQLiteStateStore(self.database)
        self.initial, self.revision = self.store.load_with_revision()
        self.calls = []

    def signals(self, binding):
        self.calls.append(binding.media_key)
        return {field: False for field in ('played', 'favorite', 'disliked', 'keep', 'keep_all', 'protected')}

    def run_preparation(self, **kwargs):
        return prepare_checkpointed_disposable_worker(root=self.root,
            config=self.fixture.config(), fetch_signals=kwargs.pop('fetch_signals', self.signals),
            clock=lambda: datetime(2026, 10, 24), **kwargs)

    def assert_media_unchanged(self):
        for library in self.fixture.libraries:
            self.assertTrue((Path(library['transient']) / 'Same (2020)').is_dir())
            self.assertEqual(list(Path(library['holding']).iterdir()), [])
            self.assertEqual(list(Path(library['keep']).iterdir()), [])
            self.assertEqual(list(Path(library['removal']).iterdir()), [])

    def test_exact_clock_checkpoint_preserves_queue_unknowns_and_rebuilds(self):
        result = self.run_preparation()
        state, revision = self.store.load_with_revision()
        self.assertTrue(result.checkpointed)
        self.assertEqual(revision, self.revision + 1)
        self.assertEqual(result.preparation.plan.revision, revision)
        self.assertEqual(result.preparation.clock_proposal.changes, ())
        self.assertEqual(self.calls, ['Same (2020)', 'TV/Same (2020)'] * 2)
        self.assertEqual(set(state['first_seen']), {'Same (2020)', 'TV/Same (2020)'})
        self.assertEqual(state['custom'], self.initial['custom'])
        self.assertEqual(state['arr_sync_pending'], self.initial['arr_sync_pending'])
        self.assert_media_unchanged()

    def test_no_changes_do_not_advance_revision_or_recollect(self):
        self.run_preparation(); self.calls.clear()
        before, revision = self.store.load_with_revision()
        result = self.run_preparation()
        self.assertFalse(result.checkpointed)
        self.assertEqual(result.final_revision, revision)
        self.assertEqual(self.calls, ['Same (2020)', 'TV/Same (2020)'])
        self.assertEqual(self.store.load_with_revision(), (before, revision))

    def test_later_library_failure_prevents_all_clock_writes(self):
        def fetch(binding):
            if binding.library == 'TV': raise RuntimeError('fixture failure')
            return self.signals(binding)
        with self.assertRaisesRegex(RuntimeError, 'fixture failure'):
            self.run_preparation(fetch_signals=fetch)
        self.assertEqual(self.store.load_with_revision(), (self.initial, self.revision))
        self.assert_media_unchanged()

    def test_intervening_revision_preserves_competing_writer(self):
        def fetch(binding):
            if not self.calls:
                other = RevisionedAuditSession(self.store)
                other.state['custom']['writer'] = True; other.checkpoint()
            return self.signals(binding)
        with self.assertRaises(RuntimeError): self.run_preparation(fetch_signals=fetch)
        state, revision = self.store.load_with_revision()
        self.assertEqual(revision, self.revision + 1)
        self.assertEqual(state['first_seen'], {})
        self.assertTrue(state['custom']['writer'])

    def test_same_revision_mutation_cannot_be_adopted(self):
        def fetch(binding):
            if not self.calls:
                with sqlite3.connect(self.database) as connection:
                    connection.execute("UPDATE extra_state SET value_json='{}' WHERE key='custom'")
            return self.signals(binding)
        with self.assertRaises(RuntimeError): self.run_preparation(fetch_signals=fetch)
        state, revision = self.store.load_with_revision()
        self.assertEqual(revision, self.revision)
        self.assertEqual(state['first_seen'], {})
        self.assertEqual(state['custom'], {})

    def test_actual_sql_abort_rolls_back_clock_checkpoint(self):
        with sqlite3.connect(self.database) as connection:
            connection.execute("CREATE TRIGGER fail_clock BEFORE INSERT ON metadata WHEN NEW.key='state_revision' BEGIN SELECT RAISE(ABORT, 'fixture'); END")
        with self.assertRaises(Exception): self.run_preparation()
        self.assertEqual(self.store.load_with_revision(), (self.initial, self.revision))
        self.assertEqual(len(self.calls), 2)
        self.assert_media_unchanged()

    def test_acknowledgement_failure_after_actual_commit_has_no_retry_or_rebuild(self):
        original = GuardedSQLiteStateStore.save_if_revision
        writes = []
        def save(store, state, revision):
            writes.append(revision)
            original(store, state, revision)
            raise RuntimeError('fixture acknowledgement lost')
        with patch.object(GuardedSQLiteStateStore, 'save_if_revision', save):
            with self.assertRaisesRegex(RuntimeError, 'acknowledgement lost'):
                self.run_preparation()
        state, revision = self.store.load_with_revision()
        self.assertEqual(writes, [self.revision])
        self.assertEqual(revision, self.revision + 1)
        self.assertEqual(len(state['first_seen']), 2)
        self.assertEqual(len(self.calls), 2)
        self.assert_media_unchanged()

    def test_new_title_during_rebuild_stops_without_second_checkpoint(self):
        def fetch(binding):
            if len(self.calls) == 2:
                (Path(self.fixture.libraries[0]['transient']) / 'New').mkdir()
            return self.signals(binding)
        with self.assertRaises(RuntimeError): self.run_preparation(fetch_signals=fetch)
        state, revision = self.store.load_with_revision()
        self.assertEqual(revision, self.revision + 1)
        self.assertNotIn('New', state['first_seen'])
        self.assert_media_unchanged()

    def test_second_scan_failure_retains_committed_clocks_without_dispatch(self):
        def fetch(binding):
            if len(self.calls) == 2: raise RuntimeError('rebuild unavailable')
            return self.signals(binding)
        with self.assertRaisesRegex(RuntimeError, 'rebuild unavailable'):
            self.run_preparation(fetch_signals=fetch)
        state, revision = self.store.load_with_revision()
        self.assertEqual(revision, self.revision + 1)
        self.assertEqual(len(state['first_seen']), 2)
        self.assert_media_unchanged()

    def test_total_deadline_is_not_restarted_for_second_scan(self):
        tick = [0]
        def fetch(binding):
            tick[0] += 1
            return self.signals(binding)
        with self.assertRaises(RuntimeError):
            self.run_preparation(fetch_signals=fetch, timer=lambda: tick[0], maximum_scan_seconds=3)
        state, revision = self.store.load_with_revision()
        self.assertEqual(revision, self.revision + 1)
        self.assertEqual(len(state['first_seen']), 2)
        self.assert_media_unchanged()


    def test_clock_checkpoint_covers_both_observed_stages_atomically(self):
        tv = self.fixture.libraries[1]
        (Path(tv['transient']) / 'Same (2020)').rename(Path(tv['holding']) / 'Same (2020)')
        result = self.run_preparation()
        state, revision = self.store.load_with_revision()
        self.assertTrue(result.checkpointed)
        self.assertEqual(revision, self.revision + 1)
        self.assertEqual(set(state['first_seen']), {'Same (2020)'})
        self.assertEqual(set(state['queued']), {'TV/Same (2020)'})
        self.assertEqual(result.preparation.plan.moves, ())

    def test_cas_writer_during_save_is_never_overwritten(self):
        original = GuardedSQLiteStateStore.save_if_revision
        def save(store, proposed, revision):
            competing = deepcopy(self.initial)
            competing['custom']['winner'] = True
            original(store, competing, revision)
            return original(store, proposed, revision)
        with patch.object(GuardedSQLiteStateStore, 'save_if_revision', save):
            with self.assertRaises(RuntimeError): self.run_preparation()
        state, revision = self.store.load_with_revision()
        self.assertEqual(revision, self.revision + 1)
        self.assertTrue(state['custom']['winner'])
        self.assertEqual(state['first_seen'], {})
        self.assertEqual(len(self.calls), 2)

    def test_rebuild_uses_new_protection_instead_of_original_signals(self):
        def fetch(binding):
            changed = len(self.calls) >= 2
            signals = self.signals(binding)
            signals['keep'] = changed
            return signals
        result = self.run_preparation(fetch_signals=fetch)
        self.assertEqual(len(result.preparation.plan.moves), 2)
        self.assertEqual([move.destination_stage for move in result.preparation.plan.moves], ['Keep', 'Keep'])
        self.assertEqual(result.preparation.plan.revision, self.revision + 1)
        self.assert_media_unchanged()

    def test_content_changes_again_after_checkpoint_stop_without_clock_loop(self):
        self.fixture.libraries[1]['new_content_resets_clock'] = True
        episode = Path(self.fixture.libraries[1]['transient']) / 'Same (2020)' / 'episode'
        episode.write_bytes(b'fixture')
        first = datetime(2026, 10, 1).timestamp()
        second = datetime(2026, 10, 20).timestamp()
        os.utime(episode, (first, first))
        session = RevisionedAuditSession(self.store)
        session.state['first_seen'] = {'Same (2020)': '2026-01-01', 'TV/Same (2020)': '2026-01-01'}
        session.checkpoint()
        base = session.revision
        def fetch(binding):
            if len(self.calls) == 2: os.utime(episode, (second, second))
            return self.signals(binding)
        with self.assertRaisesRegex(RuntimeError, 'Discovery changed after checkpoint'):
            self.run_preparation(fetch_signals=fetch)
        state, revision = self.store.load_with_revision()
        self.assertEqual(revision, base + 1)
        self.assertEqual(state['first_seen']['TV/Same (2020)'], '2026-10-01T00:00:00')
        self.assert_media_unchanged()


    def test_missing_disposable_marker_blocks_before_collection(self):
        (self.root / '.sqlite_disposable_rehearsal').unlink()
        with self.assertRaises(RuntimeError): self.run_preparation()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.store.load_with_revision(), (self.initial, self.revision))

    def test_external_stage_root_rejected_before_collection(self):
        config = self.fixture.config()
        library = config.libraries[0]
        external = replace(library, roots=tuple((stage, '/outside-stage' if stage == 'Waiting' else path)
                                               for stage, path in library.roots))
        config = replace(config, libraries=(external, config.libraries[1]))
        with self.assertRaisesRegex(ValueError, 'inside the marked lab'):
            prepare_checkpointed_disposable_worker(root=self.root, config=config,
                fetch_signals=self.signals, clock=lambda: datetime(2026, 10, 24))
        self.assertEqual(self.calls, [])
        self.assertEqual(self.store.load_with_revision(), (self.initial, self.revision))


def main():
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(
        ScheduledClockCheckpointFixtureTests))
    if not result.wasSuccessful() or result.skipped or result.testsRun != 16:
        return 1
    print(json.dumps({'status': 'scheduled_clock_checkpoint_verified', 'tests': result.testsRun,
        'fixture_only': True, 'production_authorized': False, 'production_activation': 'disabled'}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
