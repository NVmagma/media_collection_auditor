"""Real loopback coverage HTTP with disposable directories, no external collectors."""
import http.client
import json
import os
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch
from werkzeug.serving import make_server
import web


class CoverageFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='coverage.',dir='/lab')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.media=self.root/'media'
        for library in ('Movies','TV'):
            for suffix in ('','_hold','_removal','_keep'):
                (self.media/(library+suffix)).mkdir(parents=True)
            (self.media/library/'Private fixture title').mkdir()
        self.state=self.root/'state.json'
        self.state.write_text(json.dumps({'first_seen':{'Private fixture title':'2024-01-01','TV/Orphan':'2024-01-01'}}))
        self.before=self.state.read_bytes()
        self.token='synthetic_disposable_coverage_token_012345'
        env=patch.dict(os.environ,{'AUDITOR_STATE_BACKEND':'json','READ_ONLY_API_SERVICE':'true',
            'INTEGRATION_API_TOKEN':self.token,'INTEGRATION_API_COVERAGE':'true'})
        env.start();self.addCleanup(env.stop)
        for target,value in (('STATE_FILE',str(self.state)),('load_config',lambda:{'MEDIA_PATH':str(self.media),'ENABLE_MOVIES':'true','ENABLE_TV':'true'})):
            item=patch.object(web,target,value);item.start();self.addCleanup(item.stop)
        server=make_server('127.0.0.1',0,web.app,threaded=True)
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        def close():
            server.shutdown();thread.join(timeout=5);server.server_close()
        self.addCleanup(close)
        self.port=server.server_port

    def get(self,path='/api/v1/coverage',authorized=True):
        client=http.client.HTTPConnection('127.0.0.1',self.port,timeout=5)
        try:
            client.request('GET',path,headers={'Authorization':'Bearer '+self.token} if authorized else {})
            response=client.getresponse();body=response.read().decode()
            self.assertNotIn(self.token,body)
            self.assertNotIn(str(self.media),body)
            self.assertNotIn('Private fixture title',body)
            self.assertEqual(response.getheader('Cache-Control'),'no-store')
            return response.status,json.loads(body)
        finally:client.close()

    def test_auth_opt_in_and_aggregate_projection(self):
        self.assertEqual(self.get(authorized=False)[0],401)
        status,report=self.get()
        self.assertEqual(status,200);self.assertEqual(report['missing_dates'],1)
        self.assertEqual(report['records_without_stage_folder'],1)
        self.assertFalse(report['freshness_verified']);self.assertFalse(report['media_actions_authorized'])
        self.assertEqual(self.state.read_bytes(),self.before)
        os.environ['INTEGRATION_API_COVERAGE']='false'
        self.assertEqual(self.get()[0],404)

    def test_movie_filter_and_invalid_duplicate_query(self):
        status,report=self.get('/api/v1/coverage?library=Movies')
        self.assertEqual(status,200);self.assertEqual(len(report['rows']),4)
        self.assertEqual(report['missing_dates'],0)
        self.assertEqual(self.get('/api/v1/coverage?library=Movies&library=TV')[0],400)

    def test_missing_directory_keeps_totals_unknown(self):
        (self.media/'Movies_hold').rmdir()
        status,report=self.get()
        self.assertEqual(status,503);self.assertIsNone(report['missing_dates'])
        self.assertFalse(report['complete'])

    def test_missing_state_never_creates_empty_tracking(self):
        self.state.unlink()
        status,report=self.get()
        self.assertEqual(status,503);self.assertIsNone(report['rows'])
        self.assertFalse(self.state.exists())

    def test_concurrent_source_change_prevents_partial_response(self):
        original=web.filesystem_stages
        def scan(*a,**kw):
            result=original(*a,**kw);self.state.write_text('{}');return result
        with patch.object(web,'filesystem_stages',scan):
            status,report=self.get()
        self.assertEqual(status,503);self.assertIsNone(report['rows'])


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CoverageFixtureTests))
    if not result.wasSuccessful():raise SystemExit(1)
    print(json.dumps({'status':'coverage_api_http_verified','tests':result.testsRun,
        'fixture_only':True,'production_services_changed':False,'media_actions_authorized':False}))
