"""Preview-only activation/public worker/API checks using new private fixtures."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from app import sqlite_preview_activation as activation, sqlite_release_profile as build
from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_backend_gate import require_sqlite_production_activation
from app.sqlite_lock import _exclusive_lock, state_writer_lock
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_release_preparation import prepare_release_state
from app.sqlite_scheduled_observations import ScheduledRunObservations
from app.sqlite_scheduled_production import production_cycle_step
from app.sqlite_scheduled_worker_cycle import ScheduledWorkerCycle
from app.state_store import GuardedSQLiteStateStore
from scripts import sqlite_scheduled_configured_slot_fixture as configured_fixture


def prepare_case():
    case = configured_fixture.ConfiguredSlotFixtureTests(); case.setUp()
    try:
        root = case.fixture.root
        source, control, saved = root / 'release-source.json', root / 'release-control', root / 'release-config.json'
        state, _ = case.fixture.store.load_with_revision()
        raw = json.dumps(state, ensure_ascii=True).encode('ascii') + b'\n'
        source.write_bytes(raw); saved.write_text('{}')
        prepare_release_state(source=source, control_directory=control,
            expected_source_sha256=hashlib.sha256(raw).hexdigest())
        values = dict(case.values, DRY_RUN='true', AUDITOR_STATE_BACKEND='sqlite',
            READ_ONLY_API_SERVICE='false', STATE_FILE=str(source),
            SQLITE_STATE_FILE=str(control / 'state.db'), WEB_CONFIG_FILE=str(saved), TZ='UTC')
        from app.config_store import KEYS, DEFAULTS
        for key in KEYS:
            values.setdefault(key, DEFAULTS.get(key, ''))  # Never inherit real service credentials.
        return case, source, control, saved, values
    except BaseException:
        case.doCleanups(); raise


@unittest.skipUnless(sys.platform == 'linux', 'Linux bound preview release')
class PreviewReleaseFixtureTests(unittest.TestCase):
    def setUp(self):
        self.case, self.source, self.control, self.saved, self.values = prepare_case()
        self.addCleanup(self.case.doCleanups)
        for field, value in (('PROFILE', activation.PROFILE), ('SOURCE_REVISION', 'a' * 40)):
            override = patch.object(build, field, value); override.start(); self.addCleanup(override.stop)
        self.report = activation.create_preview_binding(settings=self.values)
        self.store = GuardedSQLiteStateStore(self.control / 'state.db')
        self.before = self.store.load_with_revision()
        self.source_before = self.source.read_bytes()

    def gate(self, **changes):
        return require_sqlite_production_activation(settings=dict(self.values, **changes))

    def test_valid_binding_detaches_settings_without_payload_or_write_authority(self):
        values = self.gate(); values['DRY_RUN'] = 'false'
        self.assertEqual(self.gate()['DRY_RUN'], 'true')
        self.assertFalse(self.report['media_actions_authorized'])
        self.assertNotIn('synthetic-token', (self.control / activation.BINDING).read_text())
        with self.assertRaises(FileExistsError): activation.create_preview_binding(settings=self.values)
        self.assertEqual(self.store.load_with_revision(), self.before)
        self.assertEqual(self.case.server.calls, [])

    def test_sealed_image_ignores_environment_activation_flags_before_paths(self):
        with patch.object(build, 'PROFILE', 'sealed'), patch.dict(os.environ,
                {'SQLITE_PRODUCTION_ACTIVATION': 'true', 'SQLITE_RELEASE_PROFILE': activation.PROFILE}),\
                patch.object(activation, '_effective', side_effect=AssertionError('must stay sealed')):
            with self.assertRaisesRegex(RuntimeError, 'activation is disabled'): self.gate()

    def test_public_due_cycle_collects_only_preview_and_retains_originals(self):
        cycle, observer = ScheduledWorkerCycle(), ScheduledRunObservations()
        slot = self.case.fixture.slot
        def step(now):
            return production_cycle_step(cycle=cycle, settings=self.values, now=now,
                clock=lambda: configured_fixture.NOW, observer=observer)
        self.assertEqual(step(slot - timedelta(hours=1)).status, 'waiting')
        with patch('app.sqlite_scheduled_production._run_routed_slot_locked',
                side_effect=AssertionError('No media/Arr dispatch')):
            result = step(slot)
        self.assertEqual(result.outcome['status'], 'scheduled_preview_complete')
        self.assertEqual(len(result.outcome['proposed_moves']), 2)
        self.assertEqual(result.outcome['completed'], ())
        self.assertEqual(len(self.case.server.calls), 4)
        self.assertEqual(step(slot + timedelta(seconds=1)).status, 'waiting')
        self.assertTrue(observer.history()[0]['dry_run'])
        self.assertEqual(observer.history()[0]['moves_completed'], 0)
        self.assertEqual(self.store.load_with_revision(), self.before)
        self.assertEqual(self.source.read_bytes(), self.source_before)

    def test_unsafe_policy_flags_refused_before_scan_or_claim(self):
        for key, value in (('DRY_RUN', 'false'), ('ALLOW_PERMANENT_DELETE', 'true'),
                ('ALLOW_FILESYSTEM_DELETE', 'true'), ('ALLOW_CROSS_FILESYSTEM_MOVES', 'true'),
                ('ENABLE_SEASON_PRUNING', 'true')):
            with self.subTest(key=key), self.assertRaises(RuntimeError): self.gate(**{key: value})
        self.assertEqual(self.case.server.calls, [])
        self.assertFalse((self.control / '.sqlite_scheduled_slots').exists())

    def test_saved_config_cannot_override_dry_run_into_live(self):
        self.saved.write_text('{"DRY_RUN":"false"}')
        with self.assertRaises(RuntimeError): self.gate()

    def test_malformed_configuration_blocks_without_leaking_private_key(self):
        self.saved.write_text('{"private-token":1,"private-token":2}')
        with self.assertRaises(RuntimeError) as error: self.gate()
        self.assertNotIn('private-token', str(error.exception))

    def test_changed_original_json_refused(self):
        self.source.write_bytes(self.source_before + b' ')
        with self.assertRaises(RuntimeError): self.gate()

    def test_advanced_or_pending_database_refused_without_clearance(self):
        session = RevisionedAuditSession(self.store)
        session.state[INTENTS_KEY] = {}; session.checkpoint()
        with self.assertRaises(RuntimeError): self.gate()
        self.assertIn(INTENTS_KEY, self.store.load_with_revision()[0])

    def test_identical_database_replacement_is_not_adopted(self):
        path = self.control / 'state.db'; raw = path.read_bytes()
        path.rename(self.control / 'retained.db'); path.write_bytes(raw)
        with self.assertRaises(RuntimeError): self.gate()

    def test_same_revision_mutation_is_not_adopted(self):
        with closing(sqlite3.connect(self.control / 'state.db')) as connection, connection:
            connection.execute("INSERT INTO extra_state VALUES ('raw_preview','true')")
        with self.assertRaises(RuntimeError): self.gate()

    def test_replaced_stage_root_blocks_preview(self):
        root = Path(dict(self.case.fixture.config.libraries[0].roots)['Holding'])
        root.rename(root.with_name(root.name + '-retained')); root.mkdir()
        with self.assertRaises(RuntimeError): self.gate()

    def test_api_can_report_sqlite_while_worker_locks_are_held(self):
        from app.integration_status import read_selected_tracking_status
        with patch.dict(os.environ, self.values), state_writer_lock(self.source),\
                _exclusive_lock(self.control / '.sqlite_runner.lock', 'fixture'):
            report = read_selected_tracking_status(self.source)
        self.assertEqual(report['status'], 'advisory_only')
        self.assertEqual(report['storage_authority'], 'sqlite')
        self.assertEqual(report['production_activation'], 'preview_only')
        self.assertFalse(report['media_actions_authorized'])

    def test_image_revision_mismatch_ignores_environment_spoof(self):
        with patch.object(build, 'SOURCE_REVISION', 'b' * 40),\
                patch.dict(os.environ, {'SQLITE_RELEASE_REVISION': 'a' * 40}):
            with self.assertRaises(RuntimeError): self.gate()

    def test_missing_binding_or_database_never_creates_empty_state(self):
        binding = self.control / activation.BINDING
        raw = binding.read_bytes(); binding.unlink()
        with self.assertRaises(RuntimeError): self.gate()
        self.assertFalse(binding.exists())
        binding.write_bytes(raw)
        database = self.control / 'state.db'; database.rename(self.control / 'retained.db')
        with self.assertRaises(RuntimeError): self.gate()
        self.assertFalse(database.exists())

    def test_configuration_alias_and_mid_validation_change_are_refused(self):
        retained = self.saved.with_name('retained-config.json'); self.saved.rename(retained)
        self.saved.symlink_to(retained)
        with self.assertRaises(RuntimeError): self.gate()
        self.saved.unlink(); retained.rename(self.saved)
        effective = activation._effective
        calls = []
        def change(settings):
            calls.append(True)
            if len(calls) == 2: self.saved.write_text('{} ')
            return effective(settings)
        with patch.object(activation, '_effective', change):
            with self.assertRaises(RuntimeError): self.gate()

    def test_policy_change_after_scan_is_failed_before_completed_history(self):
        from app import sqlite_scheduled_production as worker
        run = worker._run_bound_production_slot
        def changed(**kwargs):
            result = run(**kwargs)
            self.saved.write_text('{} ')
            return result
        cycle, observer = ScheduledWorkerCycle(), ScheduledRunObservations()
        slot = self.case.fixture.slot
        production_cycle_step(cycle=cycle, settings=self.values, now=slot - timedelta(hours=1), observer=observer)
        with patch.object(worker, '_run_bound_production_slot', changed):
            with self.assertRaises(RuntimeError):
                production_cycle_step(cycle=cycle, settings=self.values, now=slot,
                    clock=lambda: configured_fixture.NOW, observer=observer)
        self.assertEqual(observer.history()[0]['result'], 'failed')
        self.assertEqual(self.store.load_with_revision(), self.before)


def actual_image_acceptance():
    if not Path(activation.__file__).is_relative_to('/app/app'):
        raise RuntimeError('Actual image application modules required')
    if build.PROFILE != activation.PROFILE or build.SOURCE_REVISION != os.environ['EXPECTED_RELEASE_REVISION']:
        raise RuntimeError('Actual immutable preview image profile required')
    case, source, control, saved, values = prepare_case()
    process = None
    original = source.read_bytes()
    before = GuardedSQLiteStateStore(control / 'state.db').load_with_revision()
    try:
        activation.create_preview_binding(settings=values)
        # Exercise a real request on this host-backed fixture, retaining the
        # active bytes and binding while the private pending file is created.
        from app.sqlite_preview_settings import request_settings, pending_request_summary, PENDING
        active_config = saved.read_bytes()
        requested = json.loads(active_config)
        requested['ENABLE_TV'] = 'false' if str(values.get('ENABLE_TV','false')).lower() == 'true' else 'true'
        assert request_settings(config_path=saved, updated=requested, environment=values)['status'] == 'requested'
        assert saved.read_bytes() == active_config
        assert (saved.parent/PENDING).stat().st_mode & 0o777 == 0o600
        assert 'ENABLE_TV' in pending_request_summary(config_path=saved,environment=values)['changed_keys']
        activation.validate_preview_activation(settings=values)
        cycle = ScheduledWorkerCycle()
        slot = case.fixture.slot
        production_cycle_step(cycle=cycle, settings=values, now=slot - timedelta(hours=1), clock=lambda: configured_fixture.NOW)
        outcome = production_cycle_step(cycle=cycle, settings=values, now=slot, clock=lambda: configured_fixture.NOW)
        assert outcome.outcome['status'] == 'scheduled_preview_complete'
        assert outcome.outcome['completed'] == () and len(case.server.calls) == 4
        case.server.calls.clear()
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0)); port = reservation.getsockname()[1]
        token = 'disposable-preview-image-token-0123456789'
        env = dict(os.environ, **values, WEB_PORT=str(port),
            WEB_SESSION_SECRET='disposable-preview-session-secret', INTEGRATION_API_TOKEN=token)
        def child(environment):
            return subprocess.Popen([sys.executable, '-B', '-m', 'app.main'], env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        def reject(environment):
            paused = child(environment)
            try:
                for _ in range(100):
                    assert paused.poll() is None, 'Paused preview must keep its web process alive'
                    try:
                        with urllib.request.urlopen(f'http://127.0.0.1:{port}/login', timeout=1) as response:
                            if response.status == 200: break
                    except (OSError, urllib.error.URLError): time.sleep(0.05)
                else: raise RuntimeError('Paused preview login unavailable')
                req = urllib.request.Request(f'http://127.0.0.1:{port}/api/v1/summary',
                    headers={'Authorization':'Bearer '+token})
                try: urllib.request.urlopen(req, timeout=1)
                except urllib.error.HTTPError as error:
                    assert error.code == 503
                    with error: assert json.loads(error.read())['status'] == 'preview_paused'
                else: raise AssertionError('Invalid preview exposed tracking')
                assert source.read_bytes() == original
                assert GuardedSQLiteStateStore(control / 'state.db').load_with_revision() == before
                assert not case.server.calls
            finally:
                paused.kill(); paused.communicate(timeout=5)
        # Invalid bindings pause scans while the web process remains available.
        path = control / activation.BINDING; retained = control / 'retained-binding.json'
        path.rename(retained)
        reject(env)
        retained.rename(path)
        reject(dict(env, AUDITOR_STATE_BACKEND='json'))
        process = child(env)
        def fetch(route, authenticated=True):
            headers = {'Authorization': 'Bearer ' + token} if authenticated else {}
            try:
                with urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{port}' + route, headers=headers), timeout=1) as response:
                    return response.status, json.loads(response.read())
            except urllib.error.HTTPError as error:
                with error: return error.code, json.loads(error.read())
        for _ in range(100):
            if process.poll() is not None: raise RuntimeError('Preview process stopped before API readiness')
            try:
                code, report = fetch('/api/v1/audit-status')
                if code == 200 and report.get('next_run'): break
            except (OSError, urllib.error.URLError): pass
            time.sleep(.1)
        else: raise RuntimeError('Preview API/coordinator did not become ready')
        assert fetch('/api/v1/summary', False)[0] == 401
        code, summary = fetch('/api/v1/summary')
        assert code == 200 and summary['storage_authority'] == 'sqlite'
        assert summary['production_activation'] == 'preview_only' and summary['freshness_verified'] is False
        assert report['last_started'] is None and report['running'] is False and case.server.calls == []
        assert datetime.fromisoformat(report['next_run']) > datetime.now(timezone.utc)
        saved.write_text('{"DRY_RUN":"false"}')
        assert fetch('/api/v1/summary')[0] == 503
        assert source.read_bytes() == original and GuardedSQLiteStateStore(control / 'state.db').load_with_revision() == before
        process.send_signal(signal.SIGINT)
        out, err = process.communicate(timeout=5)
        assert process.returncode == 0 and token not in out + err
        print(json.dumps({'status': 'actual_preview_image_verified',
            'source_revision': build.SOURCE_REVISION, 'startup_waits_for_future_slot': True,
            'unauthenticated_status': 401, 'authenticated_status': 200,
            'changed_policy_status': 503, 'clean_shutdown': True,
            'settings_request_staged': True, 'active_settings_unchanged': True,
            'pending_request_private': True,
            'fixture_only': True, 'media_actions_authorized': False}))
    finally:
        if process is not None and process.poll() is None:
            process.kill(); process.communicate(timeout=5)
        case.doCleanups()


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(PreviewReleaseFixtureTests))
    if not result.wasSuccessful() or result.testsRun != 16 or result.skipped:
        raise SystemExit(1)
    if '--actual-image' in sys.argv:
        actual_image_acceptance()
    print(json.dumps({'status': 'preview_release_verified', 'tests': result.testsRun,
        'fixture_only': True, 'media_actions_authorized': False}))
