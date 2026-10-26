"""Sealed candidate worker: configured scan, moves, queues and Arr completion."""
from copy import deepcopy
from datetime import timedelta
import json
import socket
import sys
import unittest

from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_lock import audit_run_lock
from scripts.sqlite_arr_queue_fixture import ArrQueueFixtureTests, Handler


class DeliveryHandler(Handler):
    def do_GET(self):
        if self.path in ('/api/v3/movie', '/api/v3/series'):
            return super().do_GET()
        self.server.calls.append((self.command, self.path, self.headers.get('X-Api-Key'),
                                  self.headers.get('Cache-Control'), len(self.server.jellyfin.calls)))
        service = 'radarr' if '/movie/' in self.path else 'sonarr'
        record = deepcopy(self.server.records[service][0])
        if getattr(self.server, 'hook', None) is not None: self.server.hook(self.command, self.path)
        if self.server.mode == 'readback-mismatch' and self.server.puts:
            record['path'] = '/other/Same (2020)'
        self.reply(200, record)

    def reply(self, status, record):
        raw = json.dumps(record).encode()
        self.send_response(status); self.send_header('Content-Length', str(len(raw)))
        self.end_headers(); self.wfile.write(raw)

    def do_PUT(self):
        service = 'radarr' if '/movie/' in self.path else 'sonarr'
        self.server.calls.append((self.command, self.path, self.headers.get('X-Api-Key'),
                                  self.headers.get('Cache-Control'), len(self.server.jellyfin.calls)))
        self.server.puts += 1
        state, _ = self.server.store.load_with_revision()
        self.server.intent_checks.append(state[INTENTS_KEY]['kind'] == 'arr_sync')
        self.server.records[service] = [json.loads(self.rfile.read(int(self.headers['Content-Length'])))]
        if self.server.mode == 'lost-ack' or (self.server.mode == 'lost-sonarr-ack' and service == 'sonarr'):
            self.connection.shutdown(socket.SHUT_RDWR); self.connection.close(); return
        self.reply(202 if service == 'radarr' else 200, self.server.records[service][0])


@unittest.skipUnless(sys.platform == 'linux', 'Actual configured moves require Linux')
class ScheduledArrFixtureTests(unittest.TestCase):
    def setUp(self):
        self.case = ArrQueueFixtureTests(); self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.server = self.case.server
        self.server.RequestHandlerClass = DeliveryHandler
        self.server.puts = 0; self.server.intent_checks = []; self.server.hook = None
        self.server.store = self.case.case.layout.store
        self.initial = self.server.store.load_with_revision()

    def due(self):
        return self.case.case.step(self.case.case.slot)

    def no_repeat(self):
        calls = list(self.server.calls)
        self.due()  # The cycle reports the slot already consumed without dispatch.
        self.assertEqual(calls, self.server.calls)

    def test_complete_scan_moves_both_libraries_then_delivers_each_once(self):
        result = self.due().outcome
        self.assertEqual([r['service'] for r in result['arr_completed']], ['radarr', 'sonarr'])
        state, revision = self.server.store.load_with_revision()
        self.assertEqual(revision, self.initial[1] + 12)
        self.assertEqual(result['final_revision'], revision)
        self.assertNotIn(INTENTS_KEY, state)
        self.assertNotIn('Same (2020)', state['arr_sync_pending'])
        self.assertNotIn('TV/Same (2020)', state['arr_sync_pending'])
        self.assertEqual(set(state['queued']), {'Same (2020)', 'TV/Same (2020)'})
        self.assertEqual([c[0] for c in self.server.calls], ['GET', 'GET'] + ['GET','PUT','GET','GET'] * 2)
        self.assertTrue(all(self.server.intent_checks))
        self.assertTrue(all(c[4] >= 8 for c in self.server.calls[2:]))
        self.assertEqual(self.server.records['radarr'][0]['path'], '/arr-view/Movies_hold/Same (2020)')
        self.assertEqual(self.server.records['sonarr'][0]['path'], '/arr-view/TV_hold/Same (2020)')
        self.assertEqual(self.case.case.source.read_bytes(), self.case.case.original_json)
        self.no_repeat()

    def test_lost_first_ack_preserves_both_move_clocks_and_queues(self):
        self.server.mode = 'lost-ack'
        with self.assertRaises(RuntimeError): self.due()
        state, revision = self.server.store.load_with_revision()
        self.assertEqual(revision, self.initial[1] + 7)
        self.assertEqual(state[INTENTS_KEY]['details']['service'], 'radarr')
        self.assertEqual(set(state['queued']), {'Same (2020)', 'TV/Same (2020)'})
        self.assertEqual(set(state['arr_sync_pending']), set(self.initial[0]['arr_sync_pending']) | {'Same (2020)', 'TV/Same (2020)'})
        self.assertEqual(self.server.puts, 1)
        self.no_repeat()
        calls = list(self.server.calls)
        with self.assertRaises(RuntimeError): self.case.case.step(self.case.case.slot + timedelta(days=1))
        self.assertEqual(calls, self.server.calls)

    def test_later_lost_ack_preserves_first_completion_and_second_intent(self):
        self.server.mode = 'lost-sonarr-ack'
        with self.assertRaises(RuntimeError): self.due()
        state, revision = self.server.store.load_with_revision()
        self.assertEqual(revision, self.initial[1] + 10)
        self.assertNotIn('Same (2020)', state['arr_sync_pending'])
        self.assertIn('TV/Same (2020)', state['arr_sync_pending'])
        self.assertEqual(state[INTENTS_KEY]['details']['service'], 'sonarr')
        self.assertEqual(self.server.puts, 2)
        self.assertEqual(set(state['queued']), {'Same (2020)', 'TV/Same (2020)'})
        self.no_repeat()

    def test_readback_mismatch_stops_before_sonarr_delivery(self):
        self.server.mode = 'readback-mismatch'
        with self.assertRaises(RuntimeError): self.due()
        state, _ = self.server.store.load_with_revision()
        self.assertIn(INTENTS_KEY, state)
        self.assertEqual(self.server.puts, 1)
        self.assertFalse(any('/series/' in c[1] for c in self.server.calls))
        self.no_repeat()

    def test_global_cap_prevents_tv_fetch_move_queue_and_delivery(self):
        self.case.case.values['MAX_ACTIONS_PER_RUN'] = '1'
        result = self.due().outcome
        self.assertEqual(len(result['completed']), 1)
        self.assertEqual(len(result['arr_completed']), 1)
        self.assertFalse(any('series' in c[1] for c in self.server.calls))
        self.assertTrue(self.case.case.layout.case.fixture.fixture.path(1, 'transient').is_dir())
        self.assertEqual(self.server.store.load_with_revision()[1], self.initial[1] + 6)

    def test_title_replacement_between_move_and_initial_arr_read_blocks_put(self):
        def hook(method, path):
            if '/movie/' in path:
                title = self.case.case.layout.case.fixture.fixture.path(0, 'holding')
                title.rename(title.with_name('old-title')); title.mkdir()
        self.server.hook = hook
        with self.assertRaises(RuntimeError): self.due()
        self.assertEqual(self.server.puts, 0)
        self.assertIn(INTENTS_KEY, self.server.store.load_with_revision()[0])
        self.no_repeat()

    def test_changed_fresh_protection_stops_before_any_arr_put(self):
        self.case.case.layout.case.server.mode = 'late-protect'
        result = self.due().outcome
        self.assertEqual(result['status'], 'stopped')
        self.assertEqual(result['completed'], ())
        self.assertEqual(self.server.puts, 0)
        self.assertEqual(self.server.store.load_with_revision(), self.initial)

    def test_shared_json_lock_stays_held_during_arr_http(self):
        checked = []
        def hook(method, path):
            with self.assertRaises(RuntimeError):
                with audit_run_lock(self.case.case.source):
                    pass
            checked.append(path)
        self.server.hook = hook
        self.due()
        self.assertEqual(len(checked), 6)

    def test_complete_scan_failure_never_sends_arr_or_moves(self):
        self.case.case.layout.case.server.mode = 'unauthorized'
        result = self.due().outcome
        self.assertEqual(result['completed'], ())
        self.assertEqual(result['arr_completed'], ())
        self.assertEqual(self.server.calls, [])
        self.assertEqual(self.server.store.load_with_revision(), self.initial)


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ScheduledArrFixtureTests))
    if not result.wasSuccessful() or result.testsRun != 9 or result.skipped: raise SystemExit(1)
    print(json.dumps({'status': 'scheduled_arr_worker_verified', 'tests': result.testsRun,
        'fixture_only': True, 'production_activation': 'disabled', 'production_authorized': False}))
