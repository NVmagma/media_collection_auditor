"""Test scan API responses using a local server and a temporary coordinator."""
from datetime import datetime, timezone, timedelta
import json
import os
import unittest
from unittest.mock import patch
from scripts.integration_coverage_fixture import CoverageFixtureTests
from scripts.scan_observations_fixture import ScheduledRunObservations
import web


class ScanFixtureTests(unittest.TestCase):
    setUpHTTP=CoverageFixtureTests.setUp
    get=CoverageFixtureTests.get

    def setUp(self):
        self.setUpHTTP()
        os.environ['READ_ONLY_API_SERVICE']='false'
        ticks=iter(datetime(2026,10,27,tzinfo=timezone.utc)+timedelta(seconds=n) for n in range(1000))
        self.observer=ScheduledRunObservations(clock=lambda:next(ticks))
        self.observer.observe_cycle(next_run=datetime(2026,10,28,tzinfo=timezone.utc),status='waiting')
        selected=patch.object(web,'selected_scan_capture',self.observer.capture)
        selected.start();self.addCleanup(selected.stop)

    def attempt(self,success=True):
        def execute():
            if not success:raise RuntimeError('private-error-never-output')
            return {'status':'scheduled_preview_complete','proposed_moves':('Private fixture title',),'discovery_changes':2}
        if success:
            self.observer.run_attempt(scheduled_at=datetime(2026,10,27,tzinfo=timezone.utc),execute=execute,dry_run=True)
        else:
            with self.assertRaises(RuntimeError):self.observer.run_attempt(scheduled_at=datetime(2026,10,27,tzinfo=timezone.utc),execute=execute,dry_run=True)

    def test_auth_pagination_and_outcome_filter(self):
        for success in (True,False,True):self.attempt(success)
        self.assertEqual(self.get('/api/v1/scan-history',authorized=False)[0],401)
        status,report=self.get('/api/v1/scan-history?page_size=2')
        self.assertEqual(status,200);self.assertEqual(report['total_records'],3)
        self.assertTrue(report['has_more']);self.assertEqual(len(report['items']),2)
        self.assertFalse(report['history_persistent'])
        self.assertEqual(len(self.get('/api/v1/scan-history?outcome=review')[1]['items']),1)
        self.assertEqual(self.state.read_bytes(),self.before)

    def test_proposal_counts_and_failure_never_reuses_previous_counts(self):
        self.attempt()
        status,report=self.get('/api/v1/proposals')
        self.assertEqual(status,200);self.assertEqual(report['moves_proposed'],1)
        self.assertEqual(report['discovery_changes'],2);self.assertFalse(report['media_actions_authorized'])
        self.attempt(False)
        _,report=self.get('/api/v1/proposals')
        self.assertFalse(report['preview_completed']);self.assertIsNone(report['moves_proposed'])
        self.assertNotIn('private-error-never-output',json.dumps(report))

    def test_restart_and_sidecar_do_not_reconstruct_history(self):
        with patch.object(web,'selected_scan_capture',ScheduledRunObservations().capture):
            status,report=self.get('/api/v1/scan-history')
        self.assertEqual(status,503);self.assertIsNone(report['items'])
        os.environ['READ_ONLY_API_SERVICE']='true'
        self.assertEqual(self.get('/api/v1/proposals')[0],503)

    def test_invalid_pagination_is_rejected(self):
        for query in ('page=0','page_size=21','outcome=private','page=1&page=2'):
            self.assertEqual(self.get('/api/v1/scan-history?'+query)[0],400)

    def test_running_is_separate_from_previous_recorded_attempt(self):
        self.attempt()
        def execute():
            _,report=self.get('/api/v1/proposals')
            self.assertEqual(report['current']['state'],'Running')
            self.assertEqual(report['proposal_scope'],'latest_recorded_attempt')
            return {'status':'scheduled_preview_complete'}
        self.observer.run_attempt(scheduled_at=datetime(2026,10,27,tzinfo=timezone.utc),execute=execute,dry_run=True)


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ScanFixtureTests))
    if not result.wasSuccessful():raise SystemExit(1)
    print(json.dumps({'status':'scan_api_http_verified','tests':result.testsRun,
        'fixture_only':True,'production_services_changed':False,'media_actions_authorized':False}))
