"""Configured whole-show behavior; every season stays intact, pruning refused."""
from datetime import timedelta
from http.server import BaseHTTPRequestHandler
import json
import os
import sys
from urllib.parse import parse_qs, urlsplit
import unittest

from scripts.sqlite_scheduled_configured_slot_fixture import ConfiguredSlotFixtureTests, NOW


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        self.server.calls.append((self.path, self.headers.get('X-Emby-Token')))
        if self.path == '/Users':
            data = [{'Id': 'user-one'}, {'Id': 'user-two'}]
        else:
            self.server.item_reads += 1
            query = parse_qs(urlsplit(self.path).query)
            if query.get('IncludeItemTypes') != ['Series']:
                self.send_response(400); self.end_headers(); return
            second = '/user-two/' in self.path
            tags = self.server.tags if second else []
            if self.server.late_protect and self.server.item_reads > 2:
                tags = ['custom-protect']
            row = {'Id': 'series-id', 'Type': 'Series', 'Path': '/jellyfin/Same (2020)',
                'Tags': tags, 'UserData': {'IsFavorite': second and self.server.favorite,
                                         'Played': False, 'PlayCount': 0}}
            rows = [row]
            if self.server.mixed_season:
                rows.append(dict(row, Id='season-id', Type='Season',
                                 Path='/jellyfin/Same (2020)/Season 01'))
            data = {'Items': rows, 'TotalRecordCount': len(rows)}
        raw = json.dumps(data).encode()
        self.send_response(200); self.send_header('Content-Length', str(len(raw)))
        self.end_headers(); self.wfile.write(raw)


@unittest.skipUnless(sys.platform == 'linux', 'Whole-show no-replace rename requires Linux')
class TVCompatibilityFixtureTests(unittest.TestCase):
    def setUp(self):
        self.case = ConfiguredSlotFixtureTests(); self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.case.values.update(ENABLE_MOVIES='false', ENABLE_TV='true', KEEP_TAG='custom-keep',
            DISLIKE_TAG='custom-dislike', KEEP_ALL_SEASONS_TAG='custom-seasons')
        server = self.case.server
        server.RequestHandlerClass = Handler
        server.tags = []; server.favorite = False; server.mixed_season = False
        server.late_protect = False; server.item_reads = 0
        self.key = 'TV/Same (2020)'
        self.files = {'Season 01/Episode 01.mkv': b'season-one',
                      'Season 02/Episode 01.mkv': b'season-two',
                      'Season 00/Special.mkv': b'special'}
        old = (NOW - timedelta(days=300)).timestamp()
        for name, raw in self.files.items():
            path = self.title('transient') / name
            path.parent.mkdir(exist_ok=True); path.write_bytes(raw); os.utime(path, (old, old))
        self.before = self.case.fixture.store.load_with_revision()

    def title(self, stage):
        return self.case.fixture.fixture.path(1, stage)

    def intact(self, stage):
        for name, raw in self.files.items():
            self.assertEqual((self.title(stage) / name).read_bytes(), raw)
        self.assertEqual(len(list(self.title(stage).rglob('*.mkv'))), len(self.files))

    def run_slot(self):
        return self.case.run_slot()

    def moved(self, tags=(), favorite=False, expected='keep'):
        self.case.server.tags = list(tags); self.case.server.favorite = favorite
        result = self.run_slot()
        self.assertEqual(len(result['completed']), 1)
        self.assertFalse(self.title('transient').exists())
        self.intact(expected)
        return result

    def test_keep_forever_on_show_keeps_every_season(self): self.moved(['custom-protect'])
    def test_configured_keep_tag_keeps_every_season(self): self.moved(['custom-keep'])
    def test_favorite_from_second_user_keeps_every_season(self): self.moved(favorite=True)

    def test_favorites_disabled_uses_normal_holding_policy(self):
        self.case.values['FAVORITES_TRIGGER_KEEP'] = 'false'
        self.moved(favorite=True, expected='holding')

    def test_keep_all_seasons_in_keep_never_prunes_or_moves(self):
        self.title('transient').rename(self.title('keep'))
        state, revision = self.case.fixture.store.load_with_revision()
        state['keep_seen'][self.key] = state['first_seen'].pop(self.key)
        self.case.fixture.store.save_if_revision(state, revision)
        before = self.case.fixture.store.load_with_revision()
        self.case.server.tags = ['custom-seasons']
        result = self.run_slot()
        self.assertEqual(result['completed'], ())
        self.assertEqual(self.case.fixture.store.load_with_revision(), before)
        self.intact('keep')

    def test_dislike_moves_young_show_early_without_pruning(self):
        state, revision = self.case.fixture.store.load_with_revision()
        state['first_seen'][self.key] = (NOW - timedelta(days=1)).isoformat()
        self.case.fixture.store.save_if_revision(state, revision)
        self.moved(['custom-dislike'], expected='holding')

    def test_unexpected_season_response_cannot_stand_in_for_show_protection(self):
        self.case.server.mixed_season = True
        result = self.run_slot()
        self.assertEqual(result['completed'], ())
        self.assertEqual(self.case.fixture.store.load_with_revision(), self.before)
        self.intact('transient')

    def test_enabled_pruning_rejected_before_claim_or_http(self):
        self.case.values['ENABLE_SEASON_PRUNING'] = 'true'
        with self.assertRaises(ValueError): self.run_slot()
        self.assertEqual(self.case.server.calls, [])
        self.assertEqual(self.case.fixture.claims(), [])
        self.assertEqual(self.case.fixture.store.load_with_revision(), self.before)
        self.intact('transient')

    def test_new_episode_resets_clock_before_any_whole_show_move(self):
        self.case.values['TV_NEW_EPISODES_RESET_CLOCK'] = 'true'
        path = self.title('transient') / 'Season 02/Episode 02.mkv'
        path.write_bytes(b'new-episode')
        fresh = NOW - timedelta(days=1)
        os.utime(path, (fresh.timestamp(), fresh.timestamp()))
        for directory in self.title('transient').iterdir():
            if directory.is_dir():
                old = (NOW - timedelta(days=300)).timestamp()
                os.utime(directory, (old, old))
        result = self.run_slot()
        self.assertEqual(result['completed'], ())
        self.assertTrue(result['clock_checkpointed'])
        state, _ = self.case.fixture.store.load_with_revision()
        self.assertEqual(state['first_seen'][self.key], fresh.isoformat())
        self.files['Season 02/Episode 02.mkv'] = b'new-episode'
        self.intact('transient')

    def test_late_keep_forever_blocks_old_holding_decision_without_intent(self):
        self.case.server.late_protect = True
        result = self.run_slot()
        self.assertEqual(result['status'], 'stopped')
        self.assertEqual(result['completed'], ())
        self.assertEqual(self.case.fixture.store.load_with_revision(), self.before)
        self.intact('transient')


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(TVCompatibilityFixtureTests))
    if not result.wasSuccessful() or result.testsRun != 10 or result.skipped: raise SystemExit(1)
    print(json.dumps({'status': 'scheduled_tv_compatibility_verified', 'tests': result.testsRun,
        'fixture_only': True, 'production_activation': 'disabled', 'production_authorized': False,
        'season_pruning_enabled': False}))
