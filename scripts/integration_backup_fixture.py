"""Private-loopback selected-backup API tests; only new fixture packets."""
from copy import deepcopy
import hashlib
import json
import os
import unittest
from scripts.integration_coverage_fixture import CoverageFixtureTests
from app.json_backup import create_backup
from app.tracking_schema import SECTIONS


class BackupFixtureTests(unittest.TestCase):
    setUpHTTP=CoverageFixtureTests.setUp
    get=CoverageFixtureTests.get

    def setUp(self):
        self.setUpHTTP()
        self.packet=self.root/'packet'
        source=self.root/'backup-source.json';source.write_text(json.dumps({key:{} for key in SECTIONS}))
        config=self.root/'backup-config.json';config.write_text('{"private":"private-secret-never-output"}')
        create_backup(state_file=source,config_file=config,directory=self.packet)
        self.select()

    def select(self):
        info=self.packet.stat()
        os.environ['INTEGRATION_API_BACKUP_DIRECTORY']=str(self.packet)
        os.environ['INTEGRATION_API_BACKUP_IDENTITY']=f'{info.st_dev}:{info.st_ino}'
        os.environ['INTEGRATION_API_BACKUP_FINGERPRINT']=hashlib.sha256((self.packet/'backup-complete.json').read_bytes()).hexdigest()

    def test_authenticated_selected_packet_is_redacted_read_only(self):
        before={p.name:p.read_bytes() for p in self.packet.iterdir()}
        self.assertEqual(self.get('/api/v1/backup-status',authorized=False)[0],401)
        status,report=self.get('/api/v1/backup-status')
        self.assertEqual(status,200);self.assertTrue(report['packet_verified'])
        self.assertFalse(report['restore_tested']);self.assertFalse(report['restore_authorized'])
        self.assertEqual(report['current_state_comparison'],'not_performed')
        self.assertNotIn('private-secret-never-output',json.dumps(report))
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.packet.iterdir()})
        self.assertEqual(self.state.read_bytes(),self.before)

    def test_corrupt_payload_is_not_verified(self):
        (self.packet/'saved-config.json').write_text('changed-private')
        status,report=self.get('/api/v1/backup-status')
        self.assertEqual(status,503);self.assertFalse(report['packet_verified'])

    def test_missing_receipt_is_not_adopted(self):
        (self.packet/'backup-complete.json').unlink()
        self.assertEqual(self.get('/api/v1/backup-status')[0],503)
        self.assertFalse((self.packet/'backup-complete.json').exists())

    def test_legacy_receipt_without_time_has_unknown_age(self):
        path=self.packet/'backup-complete.json'
        receipt=json.loads(path.read_bytes());receipt.pop('captured_at',None)
        path.write_text(json.dumps(receipt));self.select()
        status,report=self.get('/api/v1/backup-status')
        self.assertEqual(status,200);self.assertIsNone(report['age_seconds'])
        self.assertEqual(report['capture_time_status'],'unknown')

    def test_partial_selection_and_query_path_are_rejected(self):
        os.environ['INTEGRATION_API_BACKUP_FINGERPRINT']='invalid'
        self.assertEqual(self.get('/api/v1/backup-status')[0],503)
        self.assertEqual(self.get('/api/v1/backup-status?directory=/other')[0],400)


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(BackupFixtureTests))
    if not result.wasSuccessful():raise SystemExit(1)
    print(json.dumps({'status':'backup_status_api_http_verified','tests':result.testsRun,
        'fixture_only':True,'production_services_changed':False,'restore_authorized':False}))
