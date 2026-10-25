"""Disposable offline installation/recovery; no Docker or host service controls."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch

from app import sqlite_preview_install as install, sqlite_release_profile as profile
from app.sqlite_preview_activation import PROFILE, validate_preview_activation
from app.state_store import GuardedSQLiteStateStore
from scripts.sqlite_preview_release_fixture import prepare_case
from scripts.sqlite_preview_cutover_fixture import PreviewCutoverFixtureTests, OLD


@unittest.skipUnless(sys.platform == 'linux', 'Linux descriptor-bound offline installation')
class PreviewInstallFixtureTests(unittest.TestCase):
    def setUp(self):
        self.case, self.source, _, self.saved, self.values = prepare_case()
        self.addCleanup(self.case.doCleanups)
        self.root = self.source.parent / 'new-install-control'
        self.root.mkdir(mode=0o700)
        info = self.root.stat(); self.identity = info.st_dev, info.st_ino
        self.values['SQLITE_STATE_FILE'] = str(self.root / 'release' / 'state.db')
        self.original_config = b'{"custom_extension":{"private":"synthetic-secret"}}\n'
        self.saved.write_bytes(self.original_config)
        self.proposed = {**json.loads(self.original_config), 'DRY_RUN': 'true',
            'SQLITE_DAILY_RUN_TIME': self.values['SQLITE_DAILY_RUN_TIME'],
            'SQLITE_DAILY_RUN_TIMEZONE': self.values['SQLITE_DAILY_RUN_TIMEZONE']}
        self.original_source = self.source.read_bytes()
        for key, value in (('PROFILE', PROFILE), ('SOURCE_REVISION', 'b' * 40)):
            override = patch.object(profile, key, value); override.start(); self.addCleanup(override.stop)

    def stage(self):
        return install.stage_preview(source=self.source, config=self.saved, control_root=self.root,
            expected_control_identity=self.identity, expected_config_sha256=hashlib.sha256(self.original_config).hexdigest(),
            proposed_config=self.proposed, settings=self.values)

    def restore(self):
        return install.restore_original_settings(source=self.source, config=self.saved,
            control_root=self.root, expected_control_identity=self.identity)

    def test_fresh_source_is_backed_up_and_bound_without_advancing_clocks_or_http(self):
        changed = json.loads(self.original_source); changed['unknown_latest'] = {'clock': 'newest'}
        fresh = json.dumps(changed).encode(); self.source.write_bytes(fresh)
        report = self.stage()
        self.assertEqual(report['status'], 'offline_preview_install_prepared')
        self.assertFalse(report['media_actions_authorized'])
        self.assertEqual(GuardedSQLiteStateStore(self.root / 'release' / 'state.db').load_with_revision(), (changed, 0))
        self.assertEqual(self.source.read_bytes(), fresh)
        self.assertEqual((self.root / 'release' / 'original-state.json').read_bytes(), fresh)
        self.assertEqual((self.root / install.CONFIG_BACKUP).read_bytes(), self.original_config)
        self.assertEqual(json.loads(self.saved.read_bytes())['custom_extension'], self.proposed['custom_extension'])
        validate_preview_activation(settings=self.values)
        self.assertEqual(self.case.server.calls, [])

    def test_successful_settings_recovery_preserves_json_sql_and_private_metadata(self):
        self.stage(); database = self.root / 'release' / 'state.db'
        before = GuardedSQLiteStateStore(database).load_with_revision()
        report = self.restore()
        self.assertEqual(report['status'], 'original_settings_restored_not_started')
        self.assertFalse(report['service_actions_performed'])
        self.assertEqual(self.saved.read_bytes(), self.original_config)
        self.assertEqual(self.source.read_bytes(), self.original_source)
        self.assertEqual(GuardedSQLiteStateStore(database).load_with_revision(), before)
        self.assertEqual(self.case.server.calls, [])

    def test_changed_original_settings_block_before_any_control_write(self):
        self.saved.write_text('{"changed":true}')
        with self.assertRaisesRegex(RuntimeError, 'Reviewed saved settings changed'): self.stage()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_changed_control_identity_blocks_without_writing_replacement(self):
        self.identity = self.identity[0], self.identity[1] + 1
        with self.assertRaises(RuntimeError): self.stage()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_unsafe_proposed_policy_blocks_before_backup_or_settings_change(self):
        self.proposed['DRY_RUN'] = 'false'
        with self.assertRaises(RuntimeError): self.stage()
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(self.saved.read_bytes(), self.original_config)

    def test_partial_request_is_retained_and_never_reused(self):
        def fault(phase):
            if phase == 'after_request': raise RuntimeError('simulated interruption')
        with patch.object(install, '_boundary', fault):
            with self.assertRaises(RuntimeError): self.stage()
        self.assertTrue((self.root / install.REQUEST).exists())
        self.assertFalse((self.root / install.COMPLETE).exists())
        self.assertEqual(self.saved.read_bytes(), self.original_config)
        with self.assertRaises(RuntimeError): self.stage()

    def test_failure_after_settings_change_requires_explicit_verified_recovery(self):
        def fault(phase):
            if phase == 'after_config': raise RuntimeError('simulated interruption')
        with patch.object(install, '_boundary', fault):
            with self.assertRaises(RuntimeError): self.stage()
        self.assertNotEqual(self.saved.read_bytes(), self.original_config)
        self.assertFalse((self.root / install.COMPLETE).exists())
        with self.assertRaises(RuntimeError): self.stage()
        self.restore()
        self.assertEqual(self.saved.read_bytes(), self.original_config)

    def test_changed_settings_are_not_overwritten_by_recovery(self):
        self.stage(); self.saved.write_text('{"user_edit":"retain"}')
        with self.assertRaises(RuntimeError): self.restore()
        self.assertEqual(self.saved.read_text(), '{"user_edit":"retain"}')
        self.assertFalse((self.root / install.ROLLBACK_REQUEST).exists())

    def test_advanced_sql_requires_latest_state_export_and_cannot_restore_old_settings(self):
        self.stage(); store = GuardedSQLiteStateStore(self.root / 'release' / 'state.db')
        snapshot, revision = store.load_with_revision()
        store.save_if_revision(snapshot, revision)
        with self.assertRaises(RuntimeError): self.restore()
        self.assertNotEqual(self.saved.read_bytes(), self.original_config)
        self.assertFalse((self.root / install.ROLLBACK_REQUEST).exists())

    def test_same_revision_payload_mutation_cannot_restore_original_settings(self):
        self.stage(); database = self.root / 'release' / 'state.db'
        # Retain explicit connection closure on shfs; a transaction context alone
        # leaves a FUSE-hidden live database behind during directory cleanup.
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("INSERT INTO extra_state(key,value_json) VALUES('unknown_changed','true')")
        self.assertEqual(GuardedSQLiteStateStore(database).load_with_revision()[1], 0)
        with self.assertRaises(RuntimeError): self.restore()
        self.assertFalse((self.root / install.ROLLBACK_REQUEST).exists())

    def test_changed_source_blocks_recovery_without_restoring_old_clocks(self):
        self.stage(); changed = json.loads(self.original_source); changed['unknown_new'] = True
        fresh = json.dumps(changed).encode(); self.source.write_bytes(fresh)
        with self.assertRaises(RuntimeError): self.restore()
        self.assertEqual(self.source.read_bytes(), fresh)
        self.assertFalse((self.root / install.ROLLBACK_REQUEST).exists())

    def test_changed_private_plan_is_rejected_before_installation(self):
        from app import sqlite_preview_cutover as packet
        case = PreviewCutoverFixtureTests(); case.setUp(); self.addCleanup(case.doCleanups)
        case.inputs()
        packet.write_review_packet(directory=case.root, preview_image='sha256:' + 'd' * 64,
            rollback_image=OLD, control_host='/mnt/user/appdata/media_collection_auditor_sqlite_control',
            source_revision='b' * 40)
        (case.root / packet.ENV_FILE).write_text('INTEGRATION_API_TOKEN=changed\n')
        info = case.root.stat()
        with self.assertRaisesRegex(RuntimeError, 'generated deployment plan changed'):
            install.read_install_packet(directory=case.root, expected_identity=(info.st_dev, info.st_ino),
                                        preview_image='sha256:' + 'd' * 64)
        self.assertEqual(list(self.root.iterdir()), [])


def actual_image_cli():
    """Invoke the packaged CLI with actual private Docker bind layout, never mocks."""
    from app import sqlite_preview_cutover as packet
    from app.sqlite_preview_activation import _revision
    revision = _revision()
    if revision != os.environ['EXPECTED_RELEASE_REVISION']:
        raise RuntimeError('Exact baked preview revision required')
    image = os.environ['EXPECTED_PREVIEW_IMAGE']
    root, logs, control = Path('/packet'), Path('/app/logs'), Path('/sqlite-control')
    case = PreviewCutoverFixtureTests(); case.setUp()
    try:
        case.root = root
        case.inputs()
        report = packet.write_review_packet(directory=root, preview_image=image, rollback_image=OLD,
            control_host='/mnt/user/appdata/media_collection_auditor_sqlite_control', source_revision=revision)
        logs.joinpath('auditor_config.json').write_bytes(root.joinpath('original-config.json').read_bytes())
        # Simulate a later stopped-writer snapshot, preserving the new data rather
        # than migrating the earlier running-observation payload.
        fresh = json.loads(root.joinpath('source-observed.json').read_bytes())
        fresh['latest_at_cutover'] = {'preserve': True}
        original_source = json.dumps(fresh).encode()
        logs.joinpath('auditor_state.json').write_bytes(original_source)
        env = dict(line.split('=', 1) for line in root.joinpath(packet.ENV_FILE).read_text().splitlines())
        def identity(path):
            info = path.stat(); return f'{info.st_dev}:{info.st_ino}'
        arguments = ['--packet-directory', str(root), '--expected-packet-identity', identity(root),
            '--control-root', str(control), '--expected-control-identity', identity(control), '--preview-image', image]
        def run(action):
            result = subprocess.run([sys.executable, '-B', '-m', 'app.sqlite_preview_install', action, *arguments],
                env={**os.environ, **env}, capture_output=True, timeout=30, check=True)
            return json.loads(result.stdout)
        staged = run('stage')
        assert staged['status'] == 'offline_preview_install_prepared'
        assert GuardedSQLiteStateStore(control / 'release' / 'state.db').load_with_revision() == (fresh, 0)
        check = subprocess.run([sys.executable, '-B', '-m', 'app.sqlite_preview_activation', 'check'],
            env={**os.environ, **env}, capture_output=True, timeout=30, check=True)
        assert json.loads(check.stdout)['status'] == 'preview_binding_valid'
        restored = run('restore-settings')
        assert restored['status'] == 'original_settings_restored_not_started'
        assert logs.joinpath('auditor_config.json').read_bytes() == root.joinpath('original-config.json').read_bytes()
        assert logs.joinpath('auditor_state.json').read_bytes() == original_source
        assert GuardedSQLiteStateStore(control / 'release' / 'state.db').load_with_revision() == (fresh, 0)
        print(json.dumps({'status': 'actual_offline_install_cli_verified', 'source_revision': revision,
            'fresh_source_preserved': True, 'original_settings_restored': True,
            'fixture_only': True, 'service_actions_performed': False, 'media_actions_authorized': False}))
    finally:
        case.doCleanups()


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(PreviewInstallFixtureTests))
    if not result.wasSuccessful() or result.testsRun != 12 or result.skipped: raise SystemExit(1)
    print(json.dumps({'status': 'offline_preview_install_recovery_verified', 'tests': result.testsRun,
        'fixture_only': True, 'service_actions_performed': False, 'media_actions_authorized': False}))
    if '--actual-image' in sys.argv:
        actual_image_cli()
