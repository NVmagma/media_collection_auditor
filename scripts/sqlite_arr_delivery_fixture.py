"""Private fake Arr HTTP updates through a durable disposable SQLite intent.

Even matching readbacks retain the queue and intent: clearance is a later layer.
"""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import unittest

from app.sqlite_arr_title_transport import ArrTitleUpdate
from app.sqlite_isolated_arr_runner import deliver_isolated_arr_request
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def reply(self, status, record):
        raw = json.dumps(record).encode()
        self.send_response(status); self.send_header('Content-Length', str(len(raw)))
        self.end_headers(); self.wfile.write(raw)

    def do_GET(self):
        self.server.calls.append((self.command, self.path, self.headers.get('X-Api-Key')))
        record = deepcopy(self.server.record)
        if self.server.puts and self.server.mode == 'wrong-folder':
            record['path'] = '/arr/keep/Other'
        if self.server.puts and self.server.mode == 'second-mismatch' and self.server.readbacks == 1:
            record['monitored'] = True
        if self.server.puts:
            self.server.readbacks += 1
        if self.server.mode == 'redirect':
            self.send_response(302); self.send_header('Location', '/elsewhere'); self.end_headers(); return
        self.reply(200, record)

    def do_PUT(self):
        self.server.calls.append((self.command, self.path, self.headers.get('X-Api-Key')))
        state, _ = self.server.store.load_with_revision()
        self.server.intent_before_put = state[INTENTS_KEY]['phase'] == 'intent_recorded'
        update = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.puts += 1
        self.server.received = update
        self.server.record = update
        if self.server.mode == 'lost-ack':
            self.connection.shutdown(socket.SHUT_RDWR); self.connection.close(); return
        if self.server.mode == 'reject':
            self.reply(401, {'secret': 'must-not-escape'}); return
        # Echo desired data even when future GETs disagree: echo is not proof.
        self.reply(202 if self.server.service == 'radarr' else 200, update)


class ArrDeliveryFixtureTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix='arr-delivery.')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        (self.root / '.sqlite_disposable_rehearsal').write_text('DISPOSABLE ONLY\n')
        for stage in ('transient', 'holding', 'keep', 'removal'):
            (self.root / stage).mkdir()
        (self.root / 'keep' / 'Title (2020)').mkdir()
        self.database = self.root / 'state.db'
        self.state = {section: {} for section in SECTIONS}
        self.details = dict(service='radarr', title_id=42, root='/arr/keep', monitored=False)
        self.key = 'Title (2020)'
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.service = 'radarr'; self.server.mode = 'normal'
        self.server.calls = []; self.server.puts = 0; self.server.readbacks = 0
        self.server.intent_before_put = False
        self.server.record = {'id': 42, 'path': '/arr/holding/Title (2020)', 'monitored': True,
            'qualityProfileId': 7, 'tags': [3], 'seasons': [{'seasonNumber': 1, 'monitored': True}]}
        thread = Thread(target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(timeout=2)))

    def prepare(self, service='radarr'):
        self.server.service = service
        self.details['service'] = service
        self.key = ('TV/' if service == 'sonarr' else '') + 'Title (2020)'
        self.state['keep_seen'][self.key] = '2024-01-01T00:00:00'
        self.state['arr_sync_pending'][self.key] = dict(self.details, stage='keep')
        self.state['unknown'] = {'preserved': True}
        write_offline_snapshot(self.state, self.database)
        self.server.store = GuardedSQLiteStateStore(self.database)
        self.transport = ArrTitleUpdate(service=service,
            base_url=f'http://127.0.0.1:{self.server.server_port}', token='synthetic-secret',
            source_path='/arr/holding/Title (2020)', title_folder='Title (2020)')

    def deliver(self, **kwargs):
        return deliver_isolated_arr_request(root=self.root, database=self.database,
            operation_id='delivery-one', media_key=self.key, title_folder='Title (2020)',
            details=self.details, send=self.transport, **kwargs)

    def retained(self):
        state, _ = self.server.store.load_with_revision()
        self.assertEqual(state['arr_sync_pending'], self.state['arr_sync_pending'])
        self.assertEqual(state['keep_seen'], self.state['keep_seen'])
        self.assertEqual(state['unknown'], self.state['unknown'])
        self.assertIn(INTENTS_KEY, state)
        self.assertNotIn('synthetic-secret', json.dumps(state))
        self.assertNotIn('must-not-escape', json.dumps(state))
        calls = list(self.server.calls)
        with self.assertRaises(RuntimeError): self.deliver()
        self.assertEqual(calls, self.server.calls)
        return state

    def success(self, service):
        self.prepare(service)
        original = deepcopy(self.server.record)
        result = self.deliver()
        self.assertEqual(result['outcome'], 'acknowledged_unverified')
        route = '/api/v3/' + ('movie' if service == 'radarr' else 'series') + '/42'
        self.assertEqual([(c[0], c[1]) for c in self.server.calls], [
            ('GET', route), ('PUT', route + '?moveFiles=false'), ('GET', route), ('GET', route)])
        self.assertTrue(all(c[2] == 'synthetic-secret' for c in self.server.calls))
        original.update(path='/arr/keep/Title (2020)', monitored=False)
        self.assertEqual(self.server.received, original)
        self.assertTrue(self.server.intent_before_put)
        self.assertEqual(self.server.puts, 1)
        self.retained()

    def test_radarr_202_plus_two_fresh_readbacks_retains_pending(self): self.success('radarr')
    def test_sonarr_200_preserves_seasons_and_retains_pending(self): self.success('sonarr')

    def test_lost_ack_after_remote_update_is_not_retried_or_read_as_success(self):
        self.prepare(); self.server.mode = 'lost-ack'
        self.assertEqual(self.deliver()['outcome'], 'request_exception_unknown')
        self.assertEqual(self.server.record['path'], '/arr/keep/Title (2020)')
        self.assertEqual(self.server.puts, 1); self.assertEqual(self.server.readbacks, 0)
        self.retained()

    def test_echoed_put_cannot_mask_wrong_folder_readback(self):
        self.prepare(); self.server.mode = 'wrong-folder'
        self.assertEqual(self.deliver()['outcome'], 'request_exception_unknown')
        self.assertEqual(self.server.readbacks, 1); self.retained()

    def test_second_readback_disagreement_keeps_pending(self):
        self.prepare(); self.server.mode = 'second-mismatch'
        self.assertEqual(self.deliver()['outcome'], 'request_exception_unknown')
        self.assertEqual(self.server.readbacks, 2); self.retained()

    def test_changed_source_blocks_put(self):
        self.prepare(); self.server.record['path'] = '/elsewhere/Title (2020)'
        self.assertEqual(self.deliver()['outcome'], 'request_exception_unknown')
        self.assertEqual(self.server.puts, 0); self.retained()

    def test_http_rejection_is_redacted_and_never_retried(self):
        self.prepare(); self.server.mode = 'reject'
        self.assertEqual(self.deliver()['outcome'], 'request_exception_unknown')
        self.assertEqual(self.server.puts, 1); self.retained()

    def test_redirect_is_not_followed(self):
        self.prepare(); self.server.mode = 'redirect'
        self.assertEqual(self.deliver()['outcome'], 'request_exception_unknown')
        self.assertEqual(len(self.server.calls), 1); self.assertEqual(self.server.puts, 0); self.retained()

    def test_crash_boundary_after_send_blocks_replay(self):
        self.prepare()
        with self.assertRaisesRegex(RuntimeError, 'Injected Arr crash'):
            self.deliver(fault_at='after_send')
        self.assertEqual(self.server.puts, 1)
        state = self.retained()
        self.assertEqual(state[INTENTS_KEY]['phase'], 'intent_recorded')

    @unittest.skipUnless(hasattr(signal, 'SIGKILL'), 'SIGKILL required')
    def test_actual_sigkill_after_readback_retains_intent_and_blocks_restart(self):
        self.prepare()
        code = """
import os, signal, sys
from pathlib import Path
from app.sqlite_arr_title_transport import ArrTitleUpdate
from app.sqlite_isolated_arr_runner import deliver_isolated_arr_request
root = Path(sys.argv[1])
transport = ArrTitleUpdate(service='radarr', base_url=sys.argv[2], token='synthetic-secret',
    source_path='/arr/holding/Title (2020)', title_folder='Title (2020)')
def send(details):
    transport(details)
    os.kill(os.getpid(), signal.SIGKILL)
deliver_isolated_arr_request(root=root, database=root/'state.db', operation_id='delivery-one',
    media_key='Title (2020)', title_folder='Title (2020)',
    details=dict(service='radarr', title_id=42, root='/arr/keep', monitored=False), send=send)
"""
        result = subprocess.run([sys.executable, '-S', '-B', '-c', code, str(self.root),
            f'http://127.0.0.1:{self.server.server_port}'], capture_output=True, timeout=20)
        self.assertEqual(result.returncode, -signal.SIGKILL, result.stderr.decode())
        self.assertEqual(self.server.puts, 1)
        self.assertEqual(self.server.readbacks, 2)
        self.assertEqual(self.retained()[INTENTS_KEY]['phase'], 'intent_recorded')

    def test_stable_id_mismatch_never_updates(self):
        self.prepare(); self.server.record['id'] = 99
        self.assertEqual(self.deliver()['outcome'], 'request_exception_unknown')
        self.assertEqual(self.server.puts, 0); self.retained()


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ArrDeliveryFixtureTests))
    if not result.wasSuccessful() or result.testsRun != 11 or result.skipped: raise SystemExit(1)
    print(json.dumps({'status': 'one_shot_arr_delivery_verified', 'tests': result.testsRun,
        'queue_clearance_authorized': False, 'fixture_only': True,
        'production_authorized': False, 'production_activation': 'disabled'}))
