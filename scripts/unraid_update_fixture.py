"""Disposable CLI and real-loopback HTTP acceptance, no Docker control in Python."""
from contextlib import closing
from copy import deepcopy
import hashlib
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Thread
import unittest
from xml.etree import ElementTree as ET


def inputs():
    reference = 'ghcr.io/nvmagma/media_collection_auditor@sha256:' + 'a' * 64
    root = ET.fromstring('<Container><Name>media_collection_auditor</Name>'
        '<Network>bridge</Network><Privileged>false</Privileged>'
        '<ExtraParams>--read-only</ExtraParams><WebUI>http://[IP]:[PORT:8080]/</WebUI></Container>')
    ET.SubElement(root, 'Repository').text = reference
    env = {'AUDITOR_STATE_BACKEND': 'sqlite', 'DRY_RUN': 'true',
           'SQLITE_STATE_FILE': '/sqlite-control/release/state.db',
           'ALLOW_FILESYSTEM_DELETE': 'false', 'ALLOW_PERMANENT_DELETE': 'false',
           'ALLOW_CROSS_FILESYSTEM_MOVES': 'false', 'INTEGRATION_API_TOKEN': 'fixture-secret-never-print'}
    for key, value in env.items():
        ET.SubElement(root, 'Config', Type='Variable', Target=key).text = value
    mounts = []
    for target, mode in (('/media', 'ro'), ('/app/logs', 'rw'), ('/sqlite-control', 'rw')):
        origin = '/synthetic-only' + target
        ET.SubElement(root, 'Config', Type='Path', Target=target, Mode=mode).text = origin
        mounts.append({'Type': 'bind', 'Source': origin, 'Destination': target, 'RW': mode == 'rw'})
    ET.SubElement(root, 'Config', Type='Port', Target='8080', Mode='tcp').text = '8089'
    return root, {'Name': '/media_collection_auditor', 'Config': {'Image': reference,
        'Env': [key + '=' + value for key, value in env.items()]}, 'HostConfig': {
        'NetworkMode': 'bridge', 'Privileged': False, 'ReadonlyRootfs': True,
        'PortBindings': {'8080/tcp': [{'HostIp': '', 'HostPort': '8089'}]}}, 'Mounts': mounts}


class UnraidUpdateFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='review.', dir='/lab')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.templates = self.root / 'templates'; self.templates.mkdir()
        self.xml, self.container = inputs()

    def run_cli(self):
        (self.templates / 'my-media_collection_auditor.xml').write_bytes(ET.tostring(self.xml))
        before = {path.name: path.read_bytes() for path in self.templates.iterdir()}
        result = subprocess.run([sys.executable, '-B', '-m', 'scripts.unraid_update_review',
            '--templates', str(self.templates)], input=json.dumps([self.container]),
            text=True, capture_output=True, timeout=15)
        self.assertEqual({path.name:path.read_bytes() for path in self.templates.iterdir()}, before)
        self.assertEqual(result.stderr, '')
        self.assertNotIn('fixture-secret-never-print', result.stdout)
        self.assertNotIn('/synthetic-only', result.stdout)
        report = json.loads(result.stdout)
        self.assertFalse(report['update_authorized'])
        self.assertFalse(report['binding_verified'])
        return result.returncode, report

    def test_matching_saved_template_is_only_an_observation(self):
        code, report = self.run_cli()
        self.assertEqual(code, 0)
        self.assertEqual(report['status'], 'template_matches_observed_container')

    def test_duplicate_old_filename_blocks_despite_valid_current_template(self):
        old = deepcopy(self.xml); old.find('Repository').text = 'stale'
        (self.templates / 'my-media_archiver.xml').write_bytes(ET.tostring(old))
        code, report = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn('duplicate_internal_container_name', report['blockers'])

    def test_missing_control_mount_and_wrong_image_block(self):
        self.xml.find('Repository').text = 'wrong-image'
        self.xml.remove(self.xml.find("Config[@Target='/sqlite-control']"))
        code, report = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn('image_reference_mismatch', report['blockers'])
        self.assertIn('preview_mount_layout_missing', report['blockers'])

    def test_unsafe_media_root_and_environment_block(self):
        self.container['Mounts'][0]['RW'] = True
        self.container['HostConfig']['ReadonlyRootfs'] = False
        self.container['Config']['Env'].append('DRY_RUN=false')
        code, report = self.run_cli()
        self.assertEqual(code, 2)
        self.assertTrue({'mount_binding_mismatch', 'read_only_root_missing',
                         'preview_settings_missing_or_unsafe'} <= set(report['blockers']))

    def test_malformed_other_template_never_becomes_matching_inventory(self):
        (self.templates / 'unknown.xml').write_bytes(b'private-invalid-xml')
        code, report = self.run_cli()
        self.assertEqual(code, 2)
        self.assertEqual(report['blockers'], ['inventory_unreadable_or_unsupported'])
        self.assertEqual(report['diagnostic_stage'], 'template_inventory')
        self.assertEqual(report['inventory_errors'], {'xml_parse_failed': 1})
        self.assertEqual(report['matching_template_count'], 1)

    def test_proposed_revision_change_never_reuses_binding(self):
        from scripts.unraid_update_plan import proposed_update
        container = {**self.container, 'Image': 'sha256:' + 'a' * 64}
        image = {'Id': 'sha256:' + 'b' * 64, 'Config': {'Entrypoint': ['python', '-m', 'app.main'],
            'Cmd': None, 'StopSignal': 'SIGINT', 'Volumes': None, 'Labels': {
                'org.opencontainers.image.revision': 'c' * 40,
                'io.media-collection-auditor.sqlite-activation': 'preview-only'}}}
        result = proposed_update(container=container, image=image, packaged_profile='scheduled-preview-v1',
            packaged_revision='c' * 40, binding_revision='d' * 40, binding_validation='invalid')
        self.assertTrue(result['requires_fresh_preparation'])
        self.assertIn('candidate_source_requires_new_binding', result['blockers'])
        self.assertFalse(result['candidate_binding_verified'])
        self.assertFalse(result['update_authorized'])

    def test_actual_candidate_helper_refuses_missing_binding_without_writes(self):
        before = list(self.root.iterdir())
        result = subprocess.run([sys.executable, '-B', '-m', 'scripts.unraid_proposed_update_review'],
            input=json.dumps({'containers': [self.container], 'images': [{'Id': 'sha256:' + 'b' * 64}]}),
            text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 2)
        report = json.loads(result.stdout)
        self.assertFalse(report['candidate_binding_verified'])
        self.assertFalse(report['update_authorized'])
        self.assertIn('candidate_binding_inputs_unavailable', report['blockers'])
        self.assertNotIn('fixture-secret-never-print', result.stdout + result.stderr)
        self.assertEqual(list(self.root.iterdir()), before)

    def test_backup_retains_clocks_settings_and_unknown_fields(self):
        import hashlib
        from scripts.unraid_update_backup import SECTIONS, capture_backup, inspect_backup
        folder = self.root / 'backup'; folder.mkdir(mode=0o700)
        state = {key: {} for key in SECTIONS}
        state['first_seen'] = {'Movies/Fixture': '2020-01-02T03:04:05', 'TV/Fixture': '2021-02-03T04:05:06'}
        state['unknown-extension'] = {'value': 'fixture-secret-never-print'}
        source = {name: (b'{"private":"fixture-secret-never-print"}', (1, index)) for index, name in enumerate(
            ('saved-config.json', 'retained-source.json', 'current-binding.json'))}
        identity = folder.stat().st_dev, folder.stat().st_ino
        report = capture_backup(directory=folder, expected_identity=identity,
            container={**self.container, 'Id': 'a'*64, 'Image': 'sha256:'+'b'*64}, template=ET.tostring(self.xml),
            source_revision='c'*40, validate_current=lambda: None,
            read_snapshot=lambda: (deepcopy(state), 0), read_inputs=lambda: deepcopy(source))
        self.assertFalse(report['update_authorized'])
        self.assertEqual(json.loads((folder/'tracking-snapshot.json').read_bytes()), state)
        self.assertNotIn('fixture-secret-never-print', json.dumps(report))
        fingerprint = hashlib.sha256((folder/'backup-complete.json').read_bytes()).hexdigest()
        self.assertEqual(inspect_backup(directory=folder, expected_identity=identity,
            expected_fingerprint=fingerprint)['status'], 'preview_update_backup_verified')
        (folder/'saved-config.json').write_bytes(b'changed')
        with self.assertRaises(RuntimeError):
            inspect_backup(directory=folder, expected_identity=identity, expected_fingerprint=fingerprint)

    def test_interrupted_backup_stays_partial_and_cannot_replay(self):
        from unittest.mock import patch
        from scripts import unraid_update_backup as backup
        folder = self.root / 'partial'; folder.mkdir(mode=0o700)
        state = {key: {} for key in backup.SECTIONS}
        options = dict(directory=folder, expected_identity=(folder.stat().st_dev, folder.stat().st_ino),
            container={**self.container, 'Id': 'a'*64, 'Image': 'sha256:'+'b'*64}, template=ET.tostring(self.xml),
            source_revision='c'*40, validate_current=lambda: None, read_snapshot=lambda: (state, 0),
            read_inputs=lambda: {name: (b'{}', (1,index)) for index,name in enumerate(
                ('saved-config.json', 'retained-source.json', 'current-binding.json'))})
        with patch.object(backup, '_boundary', side_effect=RuntimeError('fixture interruption')):
            with self.assertRaises(RuntimeError): backup.capture_backup(**options)
        self.assertTrue((folder/'backup-request.json').exists())
        self.assertFalse((folder/'backup-complete.json').exists())
        with self.assertRaises(RuntimeError): backup.capture_backup(**options)

    def test_real_http_icon_has_no_login_or_token_requirement(self):
        # Static route only: no scheduler, worker, database or external service.
        import app.web as web
        from werkzeug.serving import make_server, WSGIRequestHandler
        class QuietHandler(WSGIRequestHandler):
            def log(self, *args, **kwargs):
                pass
        server = make_server('127.0.0.1', 0, web.app, request_handler=QuietHandler)
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with closing(http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)) as connection:
                connection.request('GET', '/static/auditor-icon.png')
                response = connection.getresponse(); raw = response.read()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.getheader('Content-Type'), 'image/png')
                self.assertTrue(raw.startswith(b'\x89PNG\r\n\x1a\n'))
                expected = (Path(__file__).resolve().parents[1] / 'unraid/assets/media-collection-auditor-icon.png').read_bytes()
                self.assertEqual(hashlib.sha256(raw).digest(), hashlib.sha256(expected).digest())
        finally:
            server.shutdown(); server.server_close(); worker.join(timeout=5)
        self.assertFalse(worker.is_alive())


def main():
    marker = Path('/lab/.unraid_update_fixture')
    nonce = os.environ.get('UNRAID_FIXTURE_NONCE', '')
    if not nonce or marker.read_text().strip() != nonce:
        raise RuntimeError('Marked disposable fixture required')
    from app.sqlite_release_profile import SOURCE_REVISION
    if SOURCE_REVISION != os.environ.get('EXPECTED_REVISION'):
        raise RuntimeError('Matching committed preview image required')
    from scripts.unraid_update_prepare_fixture import ReplacementPrepareTests
    suite = unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(UnraidUpdateFixtureTests),
                                unittest.defaultTestLoader.loadTestsFromTestCase(ReplacementPrepareTests)])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        return 1
    print(json.dumps({'status': 'unraid_update_fixture_verified', 'tests': result.testsRun,
        'fixture_only': True, 'production_authorized': False, 'production_activation': 'disabled',
        'service_changes_performed': False, 'acceptance_scope': 'template_image_backup_and_replacement_preparation'}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
