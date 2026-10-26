"""Disposable replacement-binding acceptance: no Docker or external HTTP calls."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from app import sqlite_release_profile as build
from app.sqlite_preview_activation import PROFILE, BINDING, validate_preview_activation
from app.sqlite_preview_install import stage_preview
from app.sqlite_release_preparation import _identity
from app.sqlite_release_recovery import _local
from app.sqlite_scheduled_paths import _open_directory
from app.state_store import GuardedSQLiteStateStore
from scripts.sqlite_preview_release_fixture import prepare_case
from scripts.unraid_update_backup import capture_backup
from scripts import unraid_update_prepare as prepare


def identity(path):
    info = Path(path).stat(); return info.st_dev, info.st_ino


@unittest.skipUnless(sys.platform == 'linux', 'Linux descriptor-bound replacement preparation')
class ReplacementPrepareTests(unittest.TestCase):
    def setUp(self):
        self.case, self.source, _, self.saved, self.env = prepare_case()
        self.addCleanup(self.case.doCleanups)
        for key, value in (('PROFILE', PROFILE), ('SOURCE_REVISION', 'a'*40)):
            override = patch.object(build, key, value); override.start(); self.addCleanup(override.stop)
        self.root = self.source.parent
        self.old_control = self.root/'original-preview-control'; self.old_control.mkdir(mode=0o700)
        self.env['SQLITE_STATE_FILE'] = str(self.old_control/'release'/'state.db')
        original = json.loads(self.source.read_bytes())
        original['unknown-extension'] = {'clock': '1999-12-31T23:59:59', 'secret': 'fixture-private-secret'}
        self.source.write_text(json.dumps(original))
        self.saved.write_text('{"custom_extension":{"secret":"fixture-private-secret"}}')
        stage_preview(source=self.source, config=self.saved, control_root=self.old_control,
            expected_control_identity=identity(self.old_control),
            expected_config_sha256=hashlib.sha256(self.saved.read_bytes()).hexdigest(),
            proposed_config=json.loads(self.saved.read_bytes()), settings=self.env)
        self.old_files = {self.source: self.source.read_bytes(), self.saved: self.saved.read_bytes()}
        self.old_files.update({path:path.read_bytes() for path in self.old_control.rglob('*') if path.is_file()})
        self.state, _ = GuardedSQLiteStateStore(self.old_control/'release'/'state.db').load_with_revision()
        self.backup = self.root/'backup'; self.backup.mkdir(mode=0o700)
        def inputs():
            result = {}
            for name, path in (('saved-config.json', self.saved), ('retained-source.json', self.source),
                               ('current-binding.json', self.old_control/'release'/BINDING)):
                parent = _open_directory(str(path.parent))
                try:
                    raw, info = _local(parent, path.name); result[name] = (raw, _identity(info))
                finally:
                    os.close(parent)
            return result
        capture_backup(directory=self.backup, expected_identity=identity(self.backup),
            container={'Name': '/media_collection_auditor', 'Id': 'a'*64, 'Image': 'sha256:'+'a'*64,
                       'Config': {'Env': [key+'='+value for key,value in self.env.items()]}},
            template=b'<Container><Name>media_collection_auditor</Name></Container>', source_revision='a'*40,
            validate_current=lambda: validate_preview_activation(settings=self.env),
            read_snapshot=lambda: GuardedSQLiteStateStore(self.old_control/'release'/'state.db').load_with_revision(),
            read_inputs=inputs)
        self.fingerprint = hashlib.sha256((self.backup/'backup-complete.json').read_bytes()).hexdigest()
        self.backup_before = {p.name:p.read_bytes() for p in self.backup.iterdir()}
        build.SOURCE_REVISION = 'b'*40
        self.logs, self.control = self.root/'replacement-logs', self.root/'replacement-control'
        self.logs.mkdir(mode=0o700); self.control.mkdir(mode=0o700)
        self.image = {'Id': 'sha256:'+'b'*64, 'Config': {'Entrypoint': ['python','-m','app.main'],
            'Cmd': None, 'StopSignal': 'SIGINT', 'Volumes': None, 'Labels': {
                'org.opencontainers.image.revision': 'b'*40,
                'io.media-collection-auditor.sqlite-activation': 'preview-only'}}}

    def prepare(self, **changes):
        args = dict(backup=self.backup, backup_identity=identity(self.backup), backup_fingerprint=self.fingerprint,
            logs=self.logs, logs_identity=identity(self.logs), control=self.control, control_identity=identity(self.control),
            candidate_image=self.image)
        args.update(changes)
        return prepare.prepare_replacement(**args)

    def unchanged(self):
        self.assertEqual({path:path.read_bytes() for path in self.old_files}, self.old_files)
        self.assertEqual({p.name:p.read_bytes() for p in self.backup.iterdir()}, self.backup_before)
        with patch.object(build, 'SOURCE_REVISION', 'a'*40):
            validate_preview_activation(settings=self.env)

    def test_new_revision_binding_preserves_all_tracking_settings_and_old_files(self):
        report = self.prepare()
        self.assertEqual(report['status'], 'replacement_preview_binding_prepared')
        self.assertFalse(report['update_authorized']); self.assertFalse(report['backup_freshness_verified'])
        self.assertNotIn('fixture-private-secret', json.dumps(report))
        self.assertEqual(GuardedSQLiteStateStore(self.control/'release'/'state.db').load_with_revision(), (self.state, 0))
        self.assertEqual(json.loads((self.logs/'auditor_config.json').read_bytes()), json.loads(self.saved.read_bytes()))
        new_env = dict(line.split('=',1) for line in (self.logs/'runtime.env').read_text().splitlines())
        validate_preview_activation(settings=new_env)
        for key in ('SQLITE_DAILY_RUN_TIME', 'SQLITE_DAILY_RUN_TIMEZONE', 'INTEGRATION_API_TOKEN'):
            self.assertEqual(new_env.get(key), self.env.get(key))
        self.assertEqual(json.loads((self.control/'release'/BINDING).read_bytes())['source_revision'], 'b'*40)
        self.unchanged()

    def test_corrupt_backup_and_wrong_fingerprint_never_write_destination(self):
        with self.assertRaises(RuntimeError): self.prepare(backup_fingerprint='f'*64)
        (self.backup/'saved-config.json').write_bytes(b'changed')
        with self.assertRaises(RuntimeError): self.prepare()
        self.assertFalse(list(self.logs.iterdir())); self.assertFalse(list(self.control.iterdir()))

    def test_wrong_candidate_contract_never_writes_destination(self):
        image = deepcopy(self.image); image['Config']['Labels']['org.opencontainers.image.revision'] = 'f'*40
        with self.assertRaises(ValueError): self.prepare(candidate_image=image)
        self.assertFalse(list(self.logs.iterdir())); self.assertFalse(list(self.control.iterdir()))
        self.unchanged()

    def test_interruption_after_binding_is_retained_without_completion_or_replay(self):
        def stop(phase):
            if phase == 'after_binding': raise RuntimeError('fixture stop')
        with patch.object(prepare, '_boundary', side_effect=stop):
            with self.assertRaises(RuntimeError): self.prepare()
        self.assertTrue((self.control/'release'/BINDING).exists())
        self.assertFalse((self.logs/prepare.COMPLETE).exists())
        with self.assertRaises(RuntimeError): self.prepare()
        self.unchanged()

    def test_occupied_destination_is_never_overwritten(self):
        (self.logs/'keep').write_bytes(b'old')
        with self.assertRaises(RuntimeError): self.prepare()
        self.assertEqual((self.logs/'keep').read_bytes(), b'old')
        self.assertFalse(list(self.control.iterdir()))
        self.unchanged()

    def test_overlapping_or_aliased_roots_never_write(self):
        with self.assertRaises(ValueError): self.prepare(logs=self.backup, logs_identity=identity(self.backup))
        self.assertFalse(list(self.control.iterdir())); self.assertFalse(list(self.logs.iterdir()))
        self.unchanged()

    def test_backup_changed_after_binding_prevents_completion(self):
        def change(phase):
            if phase == 'after_binding': (self.backup/'tracking-snapshot.json').write_bytes(b'{}')
        with patch.object(prepare, '_boundary', side_effect=change):
            with self.assertRaises(RuntimeError): self.prepare()
        self.assertFalse((self.logs/prepare.COMPLETE).exists())
        self.assertEqual({path:path.read_bytes() for path in self.old_files}, self.old_files)


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ReplacementPrepareTests))
    raise SystemExit(0 if result.wasSuccessful() else 1)
