"""Real loopback Jellyfin reads composed with actual disposable routed renames."""
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sys
from threading import Thread
from urllib.parse import parse_qs, urlsplit

import unittest

from app.sqlite_scheduled_configured_slot import run_configured_disposable_slot
from scripts.sqlite_scheduled_routed_slot_fixture import ScheduledRoutedSlotFixtureTests, NOW



class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.server.calls.append((self.path, self.headers.get('X-Emby-Token')))
        hook = getattr(self.server, 'on_request', None)
        if hook is not None:
            hook()
        if self.server.mode == 'unauthorized':
            self.send_response(401); self.end_headers(); return
        if self.path == '/Users':
            data = [{'Id': 'fixture-user'}]
        else:
            kind = parse_qs(urlsplit(self.path).query)['IncludeItemTypes'][0]
            tags = ['custom-protect'] if self.server.mode == 'late-protect' and len(self.server.calls) > 4 else []
            data = {'TotalRecordCount': 1, 'Items': [{'Id': 'id-' + kind, 'Type': kind,
                'Path': '/jellyfin/' + ('Same (2020)/movie.mkv' if kind == 'Movie' else 'Same (2020)'),
                'Tags': tags, 'UserData': {'IsFavorite': False, 'Played': False, 'PlayCount': 0}}]}
        payload = json.dumps(data).encode()
        self.send_response(200); self.send_header('Content-Length', str(len(payload)))
        self.end_headers(); self.wfile.write(payload)


@unittest.skipUnless(sys.platform == 'linux', 'Actual no-replace rename requires Linux')
class ConfiguredSlotFixtureTests(unittest.TestCase):
    def setUp(self):
        fixture = ScheduledRoutedSlotFixtureTests()
        fixture.setUp()
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.mode = 'normal'; server.calls = []
        thread = Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
        thread.start()
        values = {'SQLITE_DAILY_RUN_TIME': fixture.config.schedule.local_time,
            'SQLITE_DAILY_RUN_TIMEZONE': fixture.config.schedule.timezone_name,
            'ENABLE_TV': 'true', 'DRY_RUN': 'false', 'MAX_ACTIONS_PER_RUN': '2',
            'HOLDING_DAYS': str(fixture.config.libraries[0].holding_days),
            'TV_NEW_EPISODES_RESET_CLOCK': str(fixture.config.libraries[1].new_content_resets_clock).lower(),
            'JELLYFIN_HOST_URL': f'http://127.0.0.1:{server.server_port}',
            'JELLYFIN_API_TOKEN': 'synthetic-token', 'PROTECT_TAG': 'custom-protect'}
        for library, prefix in zip(fixture.config.libraries, ('RADARR', 'SONARR'), strict=True):
            values['MOVIE_WAIT_DAYS' if prefix == 'RADARR' else 'TV_WAIT_DAYS'] = str(library.wait_days)
            for stage, path in library.roots:
                values[f'{prefix}_{"TRANSIENT" if stage == "Waiting" else stage.upper()}_PATH'] = path
        def run():
            return run_configured_disposable_slot(root=fixture.root, settings=values,
                scheduled_at=fixture.slot, now=fixture.slot + timedelta(seconds=1), clock=lambda: NOW)
        self.addCleanup(fixture.doCleanups)
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join(timeout=2)))
        self.fixture, self.server, self.values, self.run_slot = fixture, server, values, run
    def test_configured_http_scan_and_fresh_reads_move_both_libraries(self):
        fixture, server, _, run = self.fixture, self.server, self.values, self.run_slot
        result = run()
        assert result['status'] == 'disposable_scheduled_routed_slot_complete'
        assert len(result['completed']) == 2
        assert len(server.calls) == 8
        assert all(token == 'synthetic-token' for _, token in server.calls)
        assert fixture.fixture.path(0, 'holding').is_dir()
        assert fixture.fixture.path(1, 'holding').is_dir()
        with self.assertRaises(Exception):
            run()
        assert len(server.calls) == 8


    def test_changed_configured_protection_blocks_before_intent(self):
        fixture, server, _, run = self.fixture, self.server, self.values, self.run_slot
        server.mode = 'late-protect'
        result = run()
        assert result['status'] == 'stopped'
        assert result['completed'] == ()
        assert fixture.store.load_with_revision() == (fixture.initial, fixture.revision)
        assert all(fixture.fixture.path(index, 'transient').is_dir() for index in (0, 1))
        assert len(fixture.claims()) == 1


    def test_failed_real_collection_preserves_claim_and_state(self):
        fixture, server, _, run = self.fixture, self.server, self.values, self.run_slot
        server.mode = 'unauthorized'
        result = run()
        assert result['completed'] == ()
        assert result['clock_checkpointed'] is False
        assert fixture.store.load_with_revision() == (fixture.initial, fixture.revision)
        assert len(fixture.claims()) == 1
        assert all(fixture.fixture.path(index, 'transient').is_dir() for index in (0, 1))


    def test_invalid_config_never_claims_or_requests(self):
        fixture, server, values, run = self.fixture, self.server, self.values, self.run_slot
        for invalid in ({'DRY_RUN': 'true'}, {'PROTECT_TAG': 'keep'},
                        {'JELLYFIN_HOST_URL': 'file:///tmp/fixture'}):
            with self.subTest(invalid=invalid):
                before = dict(values)
                values.update(invalid)
                with self.assertRaises(ValueError):
                    run()
                values.clear(); values.update(before)
                assert server.calls == []
                assert fixture.claims() == []


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ConfiguredSlotFixtureTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful() or result.testsRun != 4 or result.skipped:
        raise SystemExit(1)
    print(json.dumps({'status': 'configured_scheduled_slot_verified', 'tests': result.testsRun,
        'fixture_only': True, 'production_authorized': False, 'production_activation': 'disabled'}))
