"""Stdlib-only multi-library worker preparation on newly created lab paths."""
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
import unittest

from app.sqlite_scheduled_plan import ScheduledScanBlocked
from app.sqlite_scheduled_worker import configured_scheduled_worker, prepare_scheduled_worker
from app.sqlite_scheduled_jellyfin import scheduled_inventory_signal_reader
from app.sqlite_state import SECTIONS
from app.sqlite_scheduled_content import ScheduledContentBlocked


class ScheduledWorkerFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='scheduled-worker-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.libraries = []
        self.snapshot = {section: {} for section in SECTIONS}
        for name, kind, prefix in [('Movies', 'Movie', ''), ('TV', 'Series', 'TV/')]:
            library = dict(name=name, jellyfin_type=kind, state_prefix=prefix,
                           wait_days=7, new_content_resets_clock=False)
            for field in ('transient', 'holding', 'keep', 'removal'):
                path = self.root / name / field
                path.mkdir(parents=True)
                library[field] = str(path)
            (Path(library['transient']) / 'Same (2020)').mkdir()
            self.snapshot['first_seen'][prefix + 'Same (2020)'] = '2026-01-01'
            self.libraries.append(library)
        self.before = deepcopy(self.snapshot)

    def config(self, cap=10):
        return configured_scheduled_worker(libraries=self.libraries, local_time='02:00',
            timezone_name='America/Los_Angeles', holding_days=7, maximum_actions=cap)

    def prepare(self, fetch=lambda binding: {}, **kwargs):
        return prepare_scheduled_worker(config=self.config(kwargs.pop('cap', 10)),
            snapshot=self.snapshot, revision=2, fetch_signals=fetch,
            now=datetime(2026, 10, 24), **kwargs)

    def test_identical_names_route_to_separate_movie_tv_libraries(self):
        result = self.prepare()
        self.assertEqual([m.media_key for m in result.plan.moves], ['Same (2020)', 'TV/Same (2020)'])
        self.assertEqual([m.library for m in result.plan.moves], ['Movies', 'TV'])
        self.assertEqual(self.snapshot, self.before)
        self.assertFalse(result.production_authorized)
        self.assertEqual(result.production_activation, 'disabled')

    def test_shared_cap_still_collects_both_libraries(self):
        visited = []
        result = self.prepare(lambda binding: visited.append(binding.library) or {}, cap=1)
        self.assertEqual(visited, ['Movies', 'TV'])
        self.assertEqual(len(result.plan.moves), 1)
        self.assertEqual(result.plan.capped_moves, 1)

    def test_duplicate_title_in_two_stages_blocks_before_collection(self):
        (Path(self.libraries[1]['holding']) / 'Same (2020)').mkdir()
        with self.assertRaisesRegex(ScheduledScanBlocked, 'ambiguous'):
            self.prepare(lambda _: self.fail('collection before inventory validation'))

    def test_symlink_title_cannot_escape_stage(self):
        (Path(self.libraries[1]['holding']) / 'escape').symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ScheduledScanBlocked):
            self.prepare(lambda _: self.fail('unsafe title collection'))

    def test_root_replacement_during_later_library_collection_blocks(self):
        root = Path(self.libraries[0]['transient'])
        def fetch(binding):
            if binding.library == 'TV':
                root.rename(root.with_name('old')); root.mkdir()
            return {}
        with self.assertRaisesRegex(ScheduledScanBlocked, 'configured_stage_changed'):
            self.prepare(fetch)
        self.assertEqual(self.snapshot, self.before)

    def test_later_library_failure_never_returns_partial_plan(self):
        def fetch(binding):
            if binding.library == 'TV':
                raise RuntimeError('fixture coverage failure')
            return {}
        with self.assertRaisesRegex(RuntimeError, 'fixture coverage'):
            self.prepare(fetch)
        self.assertEqual(self.snapshot, self.before)

    def test_real_collector_missing_user_coverage_blocks_candidates(self):
        reader = scheduled_inventory_signal_reader(fetch=lambda *a: [], clock=lambda: datetime(2026, 10, 24))
        self.assertEqual(self.prepare(reader).plan.moves, ())

    def test_missing_clocks_reported_without_adding_state(self):
        self.snapshot['first_seen'].pop('TV/Same (2020)')
        before = deepcopy(self.snapshot)
        result = self.prepare()
        self.assertEqual(result.untracked, ('TV/Same (2020)',))
        self.assertEqual(len(result.plan.moves), 1)
        self.assertEqual(self.snapshot, before)


    def discovery(self, fetch=None):
        signals = {field: False for field in ('played', 'favorite', 'disliked', 'keep', 'keep_all', 'protected')}
        return prepare_scheduled_worker(config=self.config(), snapshot=self.snapshot,
            revision=2, fetch_signals=fetch or (lambda _: signals),
            now=datetime(2026, 10, 24), discover_clocks=True)

    def test_discovered_titles_start_now_and_do_not_move(self):
        self.snapshot['first_seen'].clear()
        result = self.discovery()
        self.assertEqual(result.plan.moves, ())
        self.assertEqual(set(result.clock_proposal.proposed_snapshot['first_seen']),
                         {'Same (2020)', 'TV/Same (2020)'})
        self.assertEqual(result.clock_proposal.proposed_snapshot['first_seen']['TV/Same (2020)'],
                         '2026-10-24T00:00:00')
        self.assertEqual(self.snapshot['first_seen'], {})

    def test_new_tv_content_suppresses_entire_old_plan(self):
        self.libraries[1]['new_content_resets_clock'] = True
        title = Path(self.libraries[1]['transient']) / 'Same (2020)'
        episode = title / 'episode.mkv'; episode.write_bytes(b'fixture')
        at = datetime(2026, 10, 1).timestamp(); os.utime(episode, (at, at))
        result = self.discovery()
        self.assertEqual(result.plan.moves, ())
        self.assertEqual(result.clock_proposal.proposed_snapshot['first_seen']['TV/Same (2020)'],
                         '2026-10-01T00:00:00')
        self.assertEqual(self.snapshot, self.before)
        self.assertEqual(episode.read_bytes(), b'fixture')

    def test_tv_content_symlink_blocks_discovery_without_state_change(self):
        self.libraries[1]['new_content_resets_clock'] = True
        title = Path(self.libraries[1]['transient']) / 'Same (2020)'
        (title / 'escape').symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ScheduledContentBlocked):
            self.discovery()
        self.assertEqual(self.snapshot, self.before)

    def test_future_tv_content_blocks_only_affected_show(self):
        self.libraries[1]['new_content_resets_clock'] = True
        episode = Path(self.libraries[1]['transient']) / 'Same (2020)' / 'episode'
        episode.write_bytes(b'fixture')
        at = datetime(2030, 1, 1).timestamp(); os.utime(episode, (at, at))
        result = self.discovery()
        self.assertEqual([move.media_key for move in result.plan.moves], ['Same (2020)'])
        self.assertEqual(result.clock_proposal.changes, ())
        self.assertEqual(result.clock_proposal.proposed_snapshot, self.before)
        self.assertEqual(episode.read_bytes(), b'fixture')
        self.assertEqual(episode.stat().st_mtime, at)
        self.assertTrue(any(key == 'TV/Same (2020)' and blockers == ('future_content_timestamp',)
            for _, key, blockers, _ in result.plan.skipped))
        self.assertEqual(self.snapshot, self.before)

    def test_empty_tv_title_does_not_rewind_existing_clock(self):
        self.libraries[1]['new_content_resets_clock'] = True
        result = self.discovery()
        self.assertEqual(result.clock_proposal.changes, ())
        self.assertEqual(len(result.plan.moves), 2)
        self.assertEqual(self.snapshot, self.before)

    def test_partial_protection_never_initializes_discovery_clock(self):
        self.snapshot['first_seen'].clear()
        result = self.discovery(lambda _: {'played': False})
        self.assertEqual(result.plan.moves, ())
        self.assertEqual(result.clock_proposal.changes, ())
        self.assertEqual(self.snapshot['first_seen'], {})


def main():
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(
        ScheduledWorkerFixtureTests))
    if not result.wasSuccessful() or result.skipped or result.testsRun != 14:
        return 1
    print(json.dumps({'status': 'scheduled_worker_preparation_verified', 'tests': result.testsRun,
        'fixture_only': True, 'production_authorized': False, 'production_activation': 'disabled'}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
