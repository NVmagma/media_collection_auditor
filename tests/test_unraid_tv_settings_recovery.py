"""Real validators and SQLite; only unrelated template inventory is synthetic."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import runpy
import sys
import unittest
from unittest.mock import patch

from app import sqlite_release_profile as build
from app.sqlite_preview_activation import PROFILE, validate_preview_activation
from app.sqlite_preview_install import stage_preview
from app.state_store import GuardedSQLiteStateStore
from scripts.sqlite_preview_release_fixture import prepare_case
from scripts.unraid_update_backup import capture_current
from scripts.unraid_update_prepare import prepare_replacement


def identity(path):
    info = Path(path).stat(); return info.st_dev, info.st_ino


@unittest.skipUnless(sys.platform == 'linux', 'Linux descriptor-bound recovery')
class ReviewedTVRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.case, self.source, _, self.saved, self.env = prepare_case(); self.addCleanup(self.case.doCleanups)
        for key, value in (('PROFILE', PROFILE), ('SOURCE_REVISION','a'*40)):
            override = patch.object(build,key,value); override.start(); self.addCleanup(override.stop)
        self.env['ENABLE_TV'] = 'false'
        self.root = self.source.parent
        self.old_control = self.root/'old-working-control'; self.old_control.mkdir(mode=0o700)
        self.env['SQLITE_STATE_FILE'] = str(self.old_control/'release'/'state.db')
        self.saved.write_text('{"ENABLE_TV":"false","DRY_RUN":"true","private_extension":"private-secret"}')
        stage_preview(source=self.source, config=self.saved, control_root=self.old_control,
            expected_control_identity=identity(self.old_control),
            expected_config_sha256=hashlib.sha256(self.saved.read_bytes()).hexdigest(),
            proposed_config=json.loads(self.saved.read_bytes()), settings=self.env)
        self.state = GuardedSQLiteStateStore(self.old_control/'release'/'state.db').load_with_revision()
        self.original_files = {self.saved:self.saved.read_bytes(), self.source:self.source.read_bytes()}
        self.original_files.update({p:p.read_bytes() for p in self.old_control.rglob('*') if p.is_file()})
        self.selected = self.root/'current-user-settings.json'
        self.selected.write_text(json.dumps({**json.loads(self.saved.read_bytes()), 'ENABLE_TV':'true'}))
        self.packet = self.root/'tv-reviewed-backup'; self.packet.mkdir(mode=0o700)
        self.container = {'Name':'/media_collection_auditor', 'Id':'a'*64, 'Image':'sha256:'+'b'*64,
            'State':{'Running':False}, 'Config':{'Env':[key+'='+value for key,value in self.env.items()]}}
        self.templates = [('current.xml', b'<Container><Name>media_collection_auditor</Name></Container>')]
        # The generic template/mount comparison has separate production-format
        # tests; these filesystem fixtures use custom paths rather than /media.
        review = {'review_update':lambda **kw: {'blockers':[]},
                  'matching_templates':lambda data:[(data[0][0],None)]}
        override = patch.object(runpy,'run_path',return_value=review); override.start(); self.addCleanup(override.stop)

    def capture(self):
        return capture_current(directory=self.packet, expected_identity=identity(self.packet), container=self.container,
            templates=self.templates, selected_settings=self.selected)

    def unchanged(self):
        self.assertEqual({p:p.read_bytes() for p in self.original_files}, self.original_files)
        validate_preview_activation(settings=self.env)

    def test_reviewed_tv_selection_keeps_valid_original_and_prepares_tv_enabled_copy(self):
        result = self.capture()
        self.assertEqual(result['reviewed_settings_change'],'enable_tv_preview')
        self.assertTrue(json.loads((self.packet/'saved-config.json').read_bytes())['ENABLE_TV']=='true')
        self.assertNotIn('private-secret',json.dumps(result))
        new_logs, new_control = self.root/'new-logs', self.root/'new-control'
        new_logs.mkdir(mode=0o700); new_control.mkdir(mode=0o700)
        image = {'Id':'sha256:'+'b'*64, 'Config':{'Entrypoint':['python','-m','app.main'], 'Cmd':None,
            'StopSignal':'SIGINT','Labels':{'org.opencontainers.image.revision':'a'*40,
            'io.media-collection-auditor.sqlite-activation':'preview-only'}}}
        prepare_replacement(backup=self.packet, backup_identity=identity(self.packet),
            backup_fingerprint=hashlib.sha256((self.packet/'backup-complete.json').read_bytes()).hexdigest(),
            logs=new_logs, logs_identity=identity(new_logs), control=new_control, control_identity=identity(new_control),
            candidate_image=image)
        env = dict(line.split('=',1) for line in (new_logs/'runtime.env').read_text().splitlines())
        self.assertEqual(validate_preview_activation(settings=env)['ENABLE_TV'],'true')
        self.assertEqual(GuardedSQLiteStateStore(new_control/'release'/'state.db').load_with_revision(),self.state)
        self.unchanged()

    def test_unreviewed_policy_change_cannot_be_bundled_with_tv_enable(self):
        self.selected.write_text(json.dumps({'ENABLE_TV':'true','DRY_RUN':'false','private_extension':'private-secret'}))
        with self.assertRaises(RuntimeError): self.capture()
        self.assertFalse(list(self.packet.iterdir())); self.unchanged()

    def test_live_original_or_invalid_old_binding_refuses_before_capture(self):
        self.container['State']['Running'] = True
        with self.assertRaises(RuntimeError): self.capture()
        self.assertFalse(list(self.packet.iterdir()))
        self.container['State']['Running'] = False
        self.source.write_bytes(b'{}')
        with self.assertRaises(RuntimeError): self.capture()
        self.assertFalse(list(self.packet.iterdir()))
