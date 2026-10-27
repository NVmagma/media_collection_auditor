"""Private-loopback selected-backup API tests; only new fixture packets."""
from copy import deepcopy
import hashlib
import json
import os
import unittest
from scripts.integration_coverage_fixture import CoverageFixtureTests
from scripts.unraid_update_backup import capture_backup,SECTIONS


class BackupFixtureTests(unittest.TestCase):
    setUpHTTP=CoverageFixtureTests.setUp
    get=CoverageFixtureTests.get

    def setUp(self):
        self.setUpHTTP()
        self.packet=self.root/'packet';self.packet.mkdir(mode=0o700)
        state={key:{} for key in SECTIONS}
        state['first_seen']={'Private fixture title':'2024-01-01'}
        inputs={key:(b'{"private":"private-secret-never-output"}',(1,n)) for n,key in enumerate(
            ('saved-config.json','retained-source.json','current-binding.json'))}
        capture_backup(directory=self.packet,expected_identity=(self.packet.stat().st_dev,self.packet.stat().st_ino),
            container={'Name':'/media_collection_auditor','Id':'a'*64,'Image':'sha256:'+'b'*64},
            template=b'<Container/>',source_revision='c'*40,validate_current=lambda:None,
            read_snapshot=lambda:(deepcopy(state),0),read_inputs=lambda:deepcopy(inputs))
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
