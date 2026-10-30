"""GET-only catalog identities committed with actual disposable move clocks."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sys
from threading import Thread
import unittest
from unittest.mock import patch

from app.sqlite_operation_coordinator import INTENTS_KEY
from scripts.sqlite_scheduled_runtime_fixture import ScheduledRuntimeFixtureTests


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        self.server.calls.append((self.command, self.path, self.headers.get('X-Api-Key'),
                                  self.headers.get('Cache-Control'), len(self.server.jellyfin.calls)))
        service = 'radarr' if self.path == '/api/v3/movie' else 'sonarr'
        if self.server.mode == 'later-failure' and service == 'sonarr':
            self.send_response(401); self.end_headers(); return
        rows = self.server.records[service]
        if self.server.mode == 'duplicate' and service == 'radarr':
            rows = rows + [dict(rows[0], id=101)]
        raw = json.dumps(rows).encode()
        self.send_response(200); self.send_header('Content-Length', str(len(raw)))
        self.end_headers(); self.wfile.write(raw)


@unittest.skipUnless(sys.platform == 'linux', 'Actual no-replace rename requires Linux')
class ArrQueueFixtureTests(unittest.TestCase):
    def setUp(self):
        self.case = ScheduledRuntimeFixtureTests(); self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server = server
        server.calls = []; server.mode = 'normal'
        server.jellyfin = self.case.layout.case.server
        server.records = {service: [{'id': ident,
            'path': self.case.values[prefix + '_TRANSIENT_PATH'] + '/Same (2020)',
            'monitored': True, 'unrelated': {'secret': 'must-not-persist'}}]
            for service, prefix, ident in (('radarr', 'RADARR', 100), ('sonarr', 'SONARR', 200))}
        thread = Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join(timeout=2)))
        for prefix in ('RADARR', 'SONARR'):
            self.case.values[prefix + '_URL'] = f'http://127.0.0.1:{server.server_port}'
            self.case.values[prefix + '_API_KEY'] = 'synthetic-' + prefix
        self.case.values['RADARR_APP_HOLDING_PATH'] = '/arr-view/Movies_hold'
        self.case.values['SONARR_APP_HOLDING_PATH'] = '/arr-view/TV_hold'

    def run_due(self):
        # This historical boundary intentionally accepts queue preparation only.
        # Full configured delivery has its own private HTTP acceptance fixture.
        with patch('app.sqlite_scheduled_production.configured_arr_delivery', return_value=None):
            return self.case.step(self.case.slot)

    def test_both_ids_and_app_paths_commit_with_their_own_move_clocks(self):
        result = self.run_due()
        self.assertEqual(len(result.outcome['completed']), 2)
        state, revision = self.case.layout.store.load_with_revision()
        for key, service, ident, root in (('Same (2020)', 'radarr', 100, '/arr-view/Movies_hold'),
                ('TV/Same (2020)', 'sonarr', 200, '/arr-view/TV_hold')):
            self.assertEqual(state['arr_sync_pending'][key], {'stage': 'holding', 'service': service,
                'title_id': ident, 'root': root, 'monitored': False})
            self.assertIn(key, state['queued'])
        self.assertNotIn(INTENTS_KEY, state)
        self.assertEqual(revision, self.case.layout.before[1] + 6)
        self.assertEqual([call[:2] for call in self.server.calls],
                         [('GET', '/api/v3/movie'), ('GET', '/api/v3/series')])
        self.assertTrue(all(call[2].startswith('synthetic-') and call[3] == 'no-cache' for call in self.server.calls))
        # One shared user list plus Movie and Series catalogs precede Arr lookup.
        self.assertEqual([call[4] for call in self.server.calls], [3, 3])
        self.assertNotIn('must-not-persist', json.dumps(state))
        self.assertEqual(self.case.source.read_bytes(), self.case.original_json)

    def test_later_service_failure_prevents_all_moves_and_retains_claim(self):
        self.server.mode = 'later-failure'
        with self.assertRaises(RuntimeError): self.run_due()
        self.assertEqual(self.case.layout.store.load_with_revision(), self.case.layout.before)
        self.assertTrue(all(self.case.layout.case.fixture.fixture.path(i, 'transient').is_dir() for i in (0, 1)))
        self.assertEqual(len(self.case.layout.claims()), 1)
        self.assertEqual(len(self.server.calls), 2)

    def test_ambiguous_folder_prevents_first_intent(self):
        self.server.mode = 'duplicate'
        with self.assertRaises(RuntimeError): self.run_due()
        self.assertEqual(self.case.layout.store.load_with_revision(), self.case.layout.before)
        self.assertEqual(len(self.server.calls), 1)

    def test_global_cap_does_not_fetch_or_queue_excluded_tv_title(self):
        self.case.values['MAX_ACTIONS_PER_RUN'] = '1'
        result = self.run_due()
        self.assertEqual(len(result.outcome['completed']), 1)
        state, _ = self.case.layout.store.load_with_revision()
        self.assertIn('Same (2020)', state['arr_sync_pending'])
        self.assertNotIn('TV/Same (2020)', state['arr_sync_pending'])
        self.assertEqual(len(self.server.calls), 1)
        self.assertTrue(self.case.layout.case.fixture.fixture.path(1, 'transient').is_dir())

    def test_partial_credentials_fail_without_arr_reads_claim_or_moves(self):
        self.case.values['RADARR_API_KEY'] = ''
        with self.assertRaises(ValueError): self.run_due()
        self.assertEqual(self.server.calls, [])
        self.assertFalse(self.case.layout.claims())
        self.assertEqual(self.case.layout.store.load_with_revision(), self.case.layout.before)

    def test_wrong_source_root_blocks_without_rewriting_remote_catalog(self):
        self.server.records['radarr'][0]['path'] = '/other/Same (2020)'
        with self.assertRaises(RuntimeError): self.run_due()
        self.assertEqual(self.case.layout.store.load_with_revision(), self.case.layout.before)
        self.assertEqual(self.server.records['radarr'][0]['path'], '/other/Same (2020)')


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ArrQueueFixtureTests))
    if not result.wasSuccessful() or result.testsRun != 6 or result.skipped: raise SystemExit(1)
    print(json.dumps({'status': 'configured_arr_queue_verified', 'tests': result.testsRun,
        'fixture_only': True, 'production_authorized': False, 'production_activation': 'disabled'}))
