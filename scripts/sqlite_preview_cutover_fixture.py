"""Offline private packet rendering; synthetic Docker metadata, no Docker API."""
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import sqlite_preview_cutover as cutover
from scripts import sqlite_preview_capture as capture_script
from scripts.sqlite_release_preparation_fixture import fixture_state

OLD = 'sha256:' + 'c' * 64
NEW = 'sha256:' + 'd' * 64
REVISION = 'a' * 40
IDENTIFIER = 'f' * 64
SECRET = 'private_fixture_token_01234567890123456789'
CONTROL = '/mnt/user/appdata/media_collection_auditor_sqlite_control'


def docker_metadata():
    return [{'Id': IDENTIFIER, 'Name': '/media_collection_auditor', 'Image': OLD,
        'State': {'Running': True},
        'Config': {'Image': 'ghcr.io/nvmagma/media_collection_auditor@sha256:' + 'e' * 64,
            'User': '', 'WorkingDir': '/app', 'Entrypoint': ['python', 'main.py'], 'Cmd': None,
            'Env': ['DRY_RUN=true', 'TZ=America/Los_Angeles', 'PYTHONPATH=/old/flat', 'PATH=/old/bin',
                'JELLYFIN_HOST_URL=http://fixture.invalid:8086', 'JELLYFIN_API_TOKEN=' + SECRET,
                'INTEGRATION_API_TOKEN=' + SECRET, 'WEB_PORT=8080'],
            'Labels': {'net.unraid.docker.managed': 'dockerman', 'private.fixture.label': SECRET,
                'org.opencontainers.image.revision': 'old-revision'}},
        'HostConfig': {'Privileged': False, 'RestartPolicy': {'Name': 'no'},
            'NetworkMode': 'bridge', 'IpcMode': 'private',
            'PortBindings': {'8080/tcp': [{'HostIp': '0.0.0.0', 'HostPort': '10012'}]},
            'LogConfig': {'Type': 'json-file', 'Config': {'max-size': '10m'}},
            'Memory': 256000000, 'PidsLimit': 64},
        'Mounts': [{'Type': 'bind', 'Destination': '/media', 'Source': '/mnt/user/media_storage',
                    'RW': True, 'Propagation': 'rprivate'},
                   {'Type': 'bind', 'Destination': '/app/logs', 'Source': '/mnt/user/appdata/media_collection_auditor',
                    'RW': True, 'Propagation': 'rprivate'}]}]


class PreviewCutoverFixtureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='cutover-packet.')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.old = docker_metadata()
        self.saved = {'DRY_RUN': 'true', 'MOVIE_WAIT_DAYS': '30', 'HOLDING_DAYS': '7',
            'custom_unknown': {'preserve': [SECRET, None]}}
        self.state = fixture_state()

    def render(self, **kwargs):
        return cutover.render_plan(original=kwargs.pop('original', self.old),
            saved=kwargs.pop('saved', self.saved), source=kwargs.pop('source', self.state),
            preview_image=NEW, rollback_image=OLD, control_host=kwargs.pop('control_host', CONTROL),
            source_revision=REVISION, **kwargs)

    def inputs(self):
        raw = {'original.inspect.json': json.dumps(self.old).encode(),
            'original-config.json': json.dumps(self.saved).encode(), 'source-observed.json': json.dumps(self.state).encode()}
        for kind, name, metadata, path in (
                ('config', 'original-config.json', 'config-metadata.json', '/app/logs/auditor_config.json'),
                ('state', 'source-observed.json', 'source-metadata.json', '/app/logs/auditor_state.json')):
            raw[metadata] = json.dumps({'kind': kind, 'path': path, 'sha256': hashlib.sha256(raw[name]).hexdigest(),
                'bytes': len(raw[name]), 'uid': 0, 'process_uid': 0, 'quiescent': False}).encode()
        for name, payload in raw.items(): (self.root / name).write_bytes(payload)
        return raw

    def write(self):
        return cutover.write_review_packet(directory=self.root, preview_image=NEW,
            rollback_image=OLD, control_host=CONTROL, source_revision=REVISION)

    def test_plan_preserves_private_settings_ports_and_original_container(self):
        old = deepcopy(self.old); saved = deepcopy(self.saved)
        report, plan, env, proposed = self.render()
        self.assertEqual(self.old, old); self.assertEqual(self.saved, saved)
        self.assertEqual(env['INTEGRATION_API_TOKEN'], SECRET)
        self.assertEqual(env['PYTHONPATH'], '/app/app:/app'); self.assertNotIn('PATH', env)
        self.assertEqual(proposed['custom_unknown'], saved['custom_unknown'])
        self.assertEqual(proposed['SQLITE_DAILY_RUN_TIME'], '02:00')
        self.assertEqual(proposed['SQLITE_DAILY_RUN_TIMEZONE'], 'America/Los_Angeles')
        self.assertFalse(report['deployment_authorized']); self.assertFalse(report['service_actions_performed'])
        self.assertNotIn(SECRET, json.dumps(report))
        args = plan['create_argv_template']
        self.assertIn('--publish=0.0.0.0:10012:8080/tcp', args)
        self.assertIn('--read-only', args)
        self.assertTrue(any('dst=/media' in arg and arg.endswith(',readonly') for arg in args))
        self.assertEqual(plan['stop_original_argv'][-1], IDENTIFIER)
        self.assertEqual(plan['start_original_argv'], ['start', IDENTIFIER])
        self.assertFalse(any('old-revision' in arg for arg in args))
        self.assertEqual(args[-1], NEW)

    def test_private_packet_is_exclusive_and_inputs_unchanged(self):
        original = self.inputs()
        report = self.write()
        for name, raw in original.items(): self.assertEqual((self.root / name).read_bytes(), raw)
        self.assertEqual((self.root / cutover.ENV_FILE).stat().st_mode & 0o777, 0o600)
        self.assertIn(SECRET, (self.root / cutover.ENV_FILE).read_text())
        self.assertNotIn(SECRET, json.dumps(report))
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        with self.assertRaisesRegex(cutover.ReviewBlocked, 'existing_packet_output'): self.write()
        self.assertEqual({p.name: p.read_bytes() for p in self.root.iterdir()}, before)

    def test_wrong_image_stopped_or_wrong_name_container_blocked(self):
        for key, value in (('Image', NEW), ('Name', '/other_container'), ('State', {'Running': False})):
            data = deepcopy(self.old); data[0][key] = value
            with self.subTest(key=key), self.assertRaises(cutover.ReviewBlocked): self.render(original=data)

    def test_extra_mount_privileged_or_autoremove_blocked(self):
        data = deepcopy(self.old); data[0]['Mounts'].append({'Destination': '/var/run/docker.sock'})
        with self.assertRaises(cutover.ReviewBlocked): self.render(original=data)
        for key in ('Privileged', 'AutoRemove'):
            data = deepcopy(self.old); data[0]['HostConfig'][key] = True
            with self.subTest(key=key), self.assertRaises(cutover.ReviewBlocked): self.render(original=data)

    def test_changed_safety_or_newline_environment_blocked(self):
        for key, value in (('DRY_RUN', 'false'), ('ALLOW_FILESYSTEM_DELETE', 'true'), ('ENABLE_SEASON_PRUNING', 'true')):
            with self.subTest(key=key), self.assertRaises(cutover.ReviewBlocked):
                self.render(saved=dict(self.saved, **{key: value}))
        data = deepcopy(self.old); data[0]['Config']['Env'].append('PRIVATE_KEY=first\nsecond')
        with self.assertRaises(cutover.ReviewBlocked): self.render(original=data)

    def test_unpublished_or_custom_network_blocks_before_stopping_anything(self):
        data = deepcopy(self.old); data[0]['HostConfig']['PortBindings'] = {}
        with self.assertRaisesRegex(cutover.ReviewBlocked, 'stable_published_api_port_required'): self.render(original=data)
        data[0]['HostConfig']['NetworkMode'] = 'unknown_custom'
        with self.assertRaisesRegex(cutover.ReviewBlocked, 'custom_network_requires_review'): self.render(original=data)

    def test_host_network_and_ipv6_ports_preserve_exact_transport(self):
        data = deepcopy(self.old); data[0]['HostConfig']['NetworkMode'] = 'host'
        self.assertIn('--network=host', self.render(original=data)[1]['create_argv_template'])
        data[0]['HostConfig']['NetworkMode'] = 'bridge'
        data[0]['HostConfig']['PortBindings']['8080/tcp'][0]['HostIp'] = '::1'
        self.assertIn('--publish=[::1]:10012:8080/tcp', self.render(original=data)[1]['create_argv_template'])

    def test_overlapping_control_or_unsupported_entrypoint_refused(self):
        with self.assertRaises(cutover.ReviewBlocked): self.render(control_host='/mnt/user/media_storage/control')
        data = deepcopy(self.old); data[0]['Config']['Entrypoint'] = ['custom-wrapper']
        with self.assertRaises(cutover.ReviewBlocked): self.render(original=data)

    def test_snapshot_metadata_mismatch_refused_without_outputs(self):
        self.inputs(); (self.root / 'source-observed.json').write_text('{}')
        with self.assertRaises(cutover.ReviewBlocked): self.write()
        self.assertFalse((self.root / cutover.ENV_FILE).exists())

    def test_packet_symlink_or_hardlink_input_refused(self):
        self.inputs()
        source = self.root / 'source-observed.json'; source.rename(self.root / 'retained.json')
        source.symlink_to(self.root / 'retained.json')
        with self.assertRaises(OSError): self.write()
        source.unlink(); os.link(self.root / 'retained.json', source)
        with self.assertRaises(RuntimeError): self.write()

    def test_packet_permissions_are_not_relaxed_or_repaired(self):
        self.inputs(); self.root.chmod(0o755)
        with self.assertRaises(cutover.ReviewBlocked): self.write()
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o755)

    def test_managed_template_capture_is_private_and_name_bound(self):
        self.inputs()
        template = self.root / 'original-template.xml'
        template.write_text('<Container><Name>media_collection_auditor</Name>'
            '<Config Type="Variable" Target="INTEGRATION_API_TOKEN">' + SECRET + '</Config></Container>')
        report = self.write()
        self.assertEqual(report['managed_template'], 'captured_for_review')
        self.assertNotIn(SECRET, json.dumps(report))

    def test_partial_packet_preserves_every_input_without_ready_report(self):
        original = self.inputs(); write = cutover._write_private
        def failed(parent, name, raw):
            if name == cutover.CONFIG_FILE: raise OSError('fixture disk failure')
            return write(parent, name, raw)
        with patch.object(cutover, '_write_private', failed):
            with self.assertRaises(OSError): self.write()
        self.assertTrue((self.root / cutover.ENV_FILE).exists())
        self.assertFalse((self.root / cutover.REPORT_FILE).exists())
        for name, raw in original.items(): self.assertEqual((self.root / name).read_bytes(), raw)

    def test_live_capture_emits_exact_private_bytes_and_separate_metadata(self):
        logs = self.root / 'app' / 'logs'; logs.mkdir(parents=True)
        raw = json.dumps({'private': SECRET}).encode()
        (logs / 'auditor_config.json').write_bytes(raw)
        original_open = os.open
        def rooted(path, flags, *args, **kwargs):
            return original_open(str(self.root) if path == '/' else path, flags, *args, **kwargs)
        output = io.TextIOWrapper(io.BytesIO(), encoding='utf-8'); errors = io.StringIO()
        with patch.object(capture_script.os, 'open', rooted), patch.object(capture_script.sys, 'stdout', output), \
                patch.object(capture_script.sys, 'stderr', errors), patch.dict(os.environ, {}, clear=True):
            capture_script.capture('config')
        self.assertEqual(output.buffer.getvalue(), raw)
        metadata = json.loads(errors.getvalue())
        self.assertEqual(metadata['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertFalse(metadata['quiescent'])
        self.assertNotIn(SECRET, errors.getvalue())

    def test_substituted_mount_identity_refused_before_any_input_read_or_write(self):
        info = self.root.stat()
        with patch.object(cutover, '_local', side_effect=AssertionError('Inputs must not be read')):
            with self.assertRaisesRegex(cutover.ReviewBlocked, 'mounted_packet_identity_mismatch'):
                cutover.write_review_packet(directory=self.root, preview_image=NEW, rollback_image=OLD,
                    control_host=CONTROL, source_revision=REVISION,
                    expected_directory_identity=(info.st_dev, info.st_ino + 1))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_bound_mount_identity_accepts_only_the_original_private_directory(self):
        self.inputs(); info = self.root.stat()
        report = cutover.write_review_packet(directory=self.root, preview_image=NEW, rollback_image=OLD,
            control_host=CONTROL, source_revision=REVISION,
            expected_directory_identity=(info.st_dev, info.st_ino))
        self.assertEqual(report['status'], 'cutover_review_prepared')

    def test_live_capture_refuses_alias_and_fifo_without_emitting_private_data(self):
        logs = self.root / 'app' / 'logs'; logs.mkdir(parents=True)
        target = self.root / 'private'; target.write_text(SECRET)
        path = logs / 'auditor_config.json'
        original_open = os.open
        def rooted(value, flags, *args, **kwargs):
            return original_open(str(self.root) if value == '/' else value, flags, *args, **kwargs)
        with patch.object(capture_script.os, 'open', rooted), patch.dict(os.environ, {}, clear=True):
            path.symlink_to(target)
            with self.assertRaises(OSError): capture_script.capture('config')
            path.unlink(); os.link(target, path)
            with self.assertRaises(RuntimeError): capture_script.capture('config')
            path.unlink(); os.mkfifo(path)
            with self.assertRaises(RuntimeError): capture_script.capture('config')


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(PreviewCutoverFixtureTests))
    if not result.wasSuccessful() or result.testsRun != 17 or result.skipped:
        raise SystemExit(1)
    print(json.dumps({'status': 'private_cutover_packet_verified', 'tests': result.testsRun,
        'fixture_only': True, 'deployment_authorized': False, 'service_actions_performed': False}))
