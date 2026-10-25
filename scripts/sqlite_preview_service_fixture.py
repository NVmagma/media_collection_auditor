"""Service transaction fault contract; synthetic engine, no Docker access."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest

from scripts.sqlite_preview_cutover_fixture import PreviewCutoverFixtureTests, OLD, NEW, REVISION, IDENTIFIER
from scripts.sqlite_preview_service import (apply_service, recover_service, Journal, read_service_history,
    NAME, LABEL)

REFERENCE = 'ghcr.io/nvmagma/media_collection_auditor@sha256:' + '9' * 64
NEW_ID = '1' * 64
REQUEST_ID = '2' * 64


class Engine:
    def __init__(self, original):
        self.containers = {IDENTIFIER: deepcopy(original)}
        self.calls = []
        self.lose_ack = None
        self.on_create = None
        self.selected_image = {'Id': NEW, 'RepoDigests': [REFERENCE], 'Config': {
            'Entrypoint': ['python', '-m', 'app.main'], 'Cmd': None, 'StopSignal': 'SIGINT',
            'Labels': {'org.opencontainers.image.revision': REVISION,
                       'io.media-collection-auditor.sqlite-activation': 'preview-only'}}}

    def image(self, reference): return deepcopy(self.selected_image)
    def inspect(self, value, optional=False):
        for identity, item in self.containers.items():
            if identity == value or item['Name'] == '/' + value: return deepcopy(item)
        if optional: return None
        raise RuntimeError('Fixture container missing')

    def effect(self, method, identity):
        self.calls.append((method, identity))
        if self.lose_ack == method: raise TimeoutError('Fixture lost acknowledgement')

    def stop(self, identity):
        self.containers[identity]['State']['Running'] = False
        self.effect('stop', identity)

    def rename(self, identity, name):
        if self.inspect(name, optional=True) is not None: raise RuntimeError('Fixture name occupied')
        self.containers[identity]['Name'] = '/' + name
        self.effect('rename', identity)

    def create(self, name, payload):
        host = deepcopy(payload['HostConfig']); config = deepcopy(payload); config.pop('HostConfig')
        self.containers[NEW_ID] = {'Id': NEW_ID, 'Image': NEW, 'Name': '/' + name,
            'State': {'Running': False}, 'Config': config, 'HostConfig': host,
            'Mounts': [{'Source': m['Source'], 'Destination': m['Target'], 'RW': not m['ReadOnly']}
                       for m in host['Mounts']]}
        if self.on_create: self.on_create(self.containers[NEW_ID])
        self.effect('create', NEW_ID)
        return NEW_ID

    def start(self, identity):
        self.containers[identity]['State']['Running'] = True
        self.effect('start', identity)


class PreviewServiceFixtureTests(unittest.TestCase):
    def setUp(self):
        self.case = PreviewCutoverFixtureTests(); self.case.setUp(); self.addCleanup(self.case.doCleanups)
        self.review, self.plan, self.env, _ = self.case.render()
        self.original = deepcopy(self.case.old[0]); self.engine = Engine(self.original)
        self.parent = os.open(self.case.root, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.parent)
        self.journal = Journal(self.parent)
        self.callbacks = []

    def stage(self):
        self.assertFalse(self.engine.inspect(IDENTIFIER)['State']['Running'])
        self.callbacks.append('stage')

    def health(self, current):
        self.assertTrue(current['State']['Running']); self.callbacks.append('health')

    def template(self): self.callbacks.append('template')

    def apply(self, **changes):
        return apply_service(engine=self.engine, journal=self.journal, captured=self.original,
            report=self.review, env=self.env, reference=REFERENCE, request_id=REQUEST_ID,
            stage=changes.get('stage', self.stage), health=changes.get('health', self.health),
            install_template=changes.get('install_template', self.template))

    def recover(self, **changes):
        request, events, new_id = read_service_history(self.parent)
        return recover_service(engine=self.engine, journal=Journal(self.parent, 'recovery'), captured=self.original,
            report=self.review, env=self.env, reference=REFERENCE, request_id=request['request_id'],
            events=events, recorded_new_id=new_id, restore_settings=changes.get('restore_settings', lambda: self.callbacks.append('restore_settings')),
            restore_template=changes.get('restore_template', lambda: self.callbacks.append('restore_template')),
            reviewed_new_id=changes.get('reviewed_new_id'))

    def test_complete_handoff_retains_original_and_never_removes_any_container(self):
        report = self.apply()
        self.assertEqual(report['status'], 'preview_service_cutover_complete')
        self.assertEqual(self.callbacks, ['stage', 'health', 'template'])
        self.assertEqual(self.engine.calls, [('stop', IDENTIFIER), ('rename', IDENTIFIER), ('create', NEW_ID), ('start', NEW_ID)])
        self.assertFalse(self.engine.inspect(IDENTIFIER)['State']['Running'])
        self.assertTrue(self.engine.inspect(NEW_ID)['State']['Running'])
        self.assertEqual(read_service_history(self.parent)[1][-1]['phase'], 'cutover_complete')

    def test_changed_live_environment_blocks_before_request_or_stop(self):
        self.engine.containers[IDENTIFIER]['Config']['Env'].append('CHANGED=true')
        with self.assertRaises(RuntimeError): self.apply()
        self.assertEqual(self.engine.calls, [])
        self.assertFalse((self.case.root / 'service-request.json').exists())

    def test_wrong_published_digest_blocks_before_any_effect(self):
        self.engine.selected_image['Id'] = OLD
        with self.assertRaises(RuntimeError): self.apply()
        self.assertEqual(self.engine.calls, [])

    def test_reserved_rollback_name_blocks_before_stop(self):
        self.engine.containers['3' * 64] = {'Name': '/' + NAME + '_rollback_' + IDENTIFIER[:12]}
        with self.assertRaises(RuntimeError): self.apply()
        self.assertEqual(self.engine.calls, [])

    def test_lost_stop_acknowledgement_never_prepares_or_retries(self):
        self.engine.lose_ack = 'stop'
        with self.assertRaises(TimeoutError): self.apply()
        self.assertEqual(self.engine.calls, [('stop', IDENTIFIER)])
        self.assertEqual(self.callbacks, [])
        self.assertEqual(read_service_history(self.parent)[1][-1]['phase'], 'original_stop_requested')

    def test_failed_offline_preparation_keeps_original_stopped_and_named(self):
        def fail(): raise OSError('Fixture preparation failed')
        with self.assertRaises(OSError): self.apply(stage=fail)
        self.assertEqual(self.engine.calls, [('stop', IDENTIFIER)])
        self.assertEqual(self.engine.inspect(IDENTIFIER)['Name'], '/' + NAME)

    def test_lost_rename_acknowledgement_never_creates_preview(self):
        self.engine.lose_ack = 'rename'
        with self.assertRaises(TimeoutError): self.apply()
        self.assertNotIn(NEW_ID, self.engine.containers)
        self.assertEqual(read_service_history(self.parent)[1][-1]['phase'], 'original_archive_requested')

    def test_lost_create_acknowledgement_requires_human_reviewed_exact_id(self):
        self.engine.lose_ack = 'create'
        with self.assertRaises(TimeoutError): self.apply()
        with self.assertRaisesRegex(RuntimeError, 'explicit preview ID review'): self.recover()
        self.assertFalse((self.case.root / 'recovery-request.json').exists())
        self.engine.lose_ack = None
        report = self.recover(reviewed_new_id=NEW_ID)
        self.assertEqual(report['status'], 'original_auditor_recovered')
        self.assertTrue(self.engine.inspect(IDENTIFIER)['State']['Running'])

    def test_lost_start_acknowledgement_never_restarts_or_automatically_restores(self):
        self.engine.lose_ack = 'start'
        with self.assertRaises(TimeoutError): self.apply()
        self.assertTrue(self.engine.inspect(NEW_ID)['State']['Running'])
        self.assertEqual(self.callbacks, ['stage'])
        self.assertEqual(read_service_history(self.parent)[1][-1]['phase'], 'preview_start_requested')

    def test_failed_health_never_installs_template_or_starts_original(self):
        def fail(current): raise RuntimeError('Fixture health failed')
        with self.assertRaises(RuntimeError): self.apply(health=fail)
        self.assertEqual(self.callbacks, ['stage'])
        self.assertFalse(self.engine.inspect(IDENTIFIER)['State']['Running'])

    def test_template_failure_never_automatically_rolls_back_healthy_preview(self):
        def fail(): self.callbacks.append('uncertain_template'); raise OSError('Fixture template acknowledgement lost')
        with self.assertRaises(OSError): self.apply(install_template=fail)
        self.assertTrue(self.engine.inspect(NEW_ID)['State']['Running'])
        self.assertEqual(read_service_history(self.parent)[1][-1]['phase'], 'managed_template_install_requested')

    def test_wrong_created_backend_is_blocked_before_start(self):
        self.engine.on_create = lambda item: item['Config']['Env'].append('AUDITOR_STATE_BACKEND=json')
        with self.assertRaises(RuntimeError): self.apply()
        self.assertFalse(self.engine.inspect(NEW_ID)['State']['Running'])

    def test_wrong_created_mount_is_blocked_before_start(self):
        self.engine.on_create = lambda item: item['Mounts'][0].update(RW=True)
        with self.assertRaises(RuntimeError): self.apply()
        self.assertFalse(self.engine.inspect(NEW_ID)['State']['Running'])

    def test_recovery_stops_preview_restores_settings_and_template_before_original_start(self):
        self.apply(); self.engine.calls.clear(); self.callbacks.clear()
        self.recover()
        self.assertEqual(self.callbacks, ['restore_settings', 'restore_template'])
        self.assertEqual(self.engine.calls, [('stop', NEW_ID), ('rename', NEW_ID), ('rename', IDENTIFIER), ('start', IDENTIFIER)])
        self.assertFalse(self.engine.inspect(NEW_ID)['State']['Running'])

    def test_recovery_advanced_state_refusal_keeps_both_workers_stopped(self):
        self.apply()
        def fail(): raise RuntimeError('Fixture advanced SQL blocks settings recovery')
        with self.assertRaises(RuntimeError): self.recover(restore_settings=fail)
        self.assertFalse(self.engine.inspect(NEW_ID)['State']['Running'])
        self.assertFalse(self.engine.inspect(IDENTIFIER)['State']['Running'])

    def test_corrupt_service_history_is_not_replayed(self):
        self.apply()
        (self.case.root / 'service-0002.json').write_text('{"phase":"other"}')
        with self.assertRaises(RuntimeError): read_service_history(self.parent)

    def test_failed_intent_persistence_never_stops_original(self):
        def fail(*args, **kwargs): raise OSError('Fixture durable journal failure')
        self.journal.event = fail
        with self.assertRaises(OSError): self.apply()
        self.assertEqual(self.engine.calls, [])
        self.assertTrue(self.engine.inspect(IDENTIFIER)['State']['Running'])
        self.assertTrue((self.case.root / 'service-request.json').exists())

    def test_actual_fixture_adapter_never_selects_production_names_or_other_ids(self):
        from scripts.sqlite_preview_service_docker_fixture import ScopedFixtureEngine
        class Observations:
            def __init__(self): self.names = []
            def inspect(self, name, optional=False): self.names.append(name); return None
        raw = Observations()
        scope = ScopedFixtureEngine(raw, NEW, Path('/private-fixture'), 'a' * 16)
        scope.original = '3' * 64
        with self.assertRaises(RuntimeError): scope.stop(IDENTIFIER)
        self.assertEqual(raw.names, [])
        self.assertIsNone(scope.inspect(NAME, optional=True))
        self.assertEqual(raw.names, ['auditor-service-' + 'a' * 16])

    def test_reordered_original_mount_records_preserve_full_identity_checks(self):
        self.engine.containers[IDENTIFIER]['Mounts'].reverse()
        self.assertEqual(self.apply()['status'], 'preview_service_cutover_complete')

    def test_changed_original_mount_mode_is_not_hidden_by_order_normalization(self):
        self.engine.containers[IDENTIFIER]['Mounts'].reverse()
        self.engine.containers[IDENTIFIER]['Mounts'][0]['RW'] = False
        with self.assertRaises(RuntimeError): self.apply()
        self.assertEqual(self.engine.calls, [])

    def test_duplicate_preview_mount_target_blocks_before_start(self):
        self.engine.on_create = lambda item: item['Mounts'].append(deepcopy(item['Mounts'][0]))
        with self.assertRaises(RuntimeError): self.apply()
        self.assertFalse(self.engine.inspect(NEW_ID)['State']['Running'])


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(PreviewServiceFixtureTests))
    if not result.wasSuccessful() or result.testsRun != 21 or result.skipped: raise SystemExit(1)
    print(json.dumps({'status': 'service_cutover_fault_contract_verified', 'tests': result.testsRun,
        'fixture_only': True, 'docker_api_accessed': False, 'production_authorized': False}))
