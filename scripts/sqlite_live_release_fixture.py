"""Actual packaged live profile, using only disposable files and private HTTP."""
from contextlib import closing
from datetime import datetime,timedelta,timezone
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
from threading import Thread
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from app import sqlite_live_binding as binding,sqlite_release_profile as build
from app.sqlite_backend_gate import require_sqlite_production_activation,require_sqlite_read_authority
from app.sqlite_live_policy import DISABLED
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_scheduled_observations import ScheduledRunObservations
from app.sqlite_scheduled_production import production_cycle_step
from app.sqlite_scheduled_worker_cycle import ScheduledWorkerCycle
from app.state_store import GuardedSQLiteStateStore
from scripts.sqlite_preview_release_fixture import prepare_case
from scripts.sqlite_scheduled_configured_slot_fixture import NOW
from scripts.sqlite_scheduled_arr_fixture import DeliveryHandler


class LiveReleaseTests(unittest.TestCase):
    def setUp(self):
        self.case,self.source,self.control,self.saved,self.values=prepare_case()
        self.addCleanup(self.case.doCleanups)
        self.values.update(DRY_RUN='false',MAX_ACTIONS_PER_RUN='1',**{key:'false' for key in DISABLED})
        self.store=GuardedSQLiteStateStore(self.control/'state.db')
        self.original=self.source.read_bytes()
        self.cycle=ScheduledWorkerCycle();self.observer=ScheduledRunObservations()
        self.bound=False

    def bind(self):
        binding.create_live_binding(settings=self.values);self.bound=True

    def step(self,now):
        return production_cycle_step(cycle=self.cycle,settings=self.values,now=now,clock=lambda:NOW,observer=self.observer)

    def due(self):
        self.assertEqual(self.step(self.case.fixture.slot-timedelta(hours=1)).status,'waiting')
        return self.step(self.case.fixture.slot)

    def arr(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),DeliveryHandler)
        server.calls=[];server.mode='normal';server.puts=0;server.intent_checks=[];server.hook=None
        server.store=self.store;server.jellyfin=self.case.server
        server.records={service:[{'id':ident,'path':self.values[prefix+'_TRANSIENT_PATH']+'/Same (2020)',
                                 'monitored':True,'unrelated':{'secret':'never-export'}}]
                        for service,prefix,ident in (('radarr','RADARR',100),('sonarr','SONARR',200))}
        thread=Thread(target=lambda:server.serve_forever(poll_interval=.01),daemon=True);thread.start()
        self.addCleanup(lambda:(server.shutdown(),server.server_close(),thread.join(timeout=2)))
        for prefix in ('RADARR','SONARR'):
            self.values[prefix+'_URL']=f'http://127.0.0.1:{server.server_port}'
            self.values[prefix+'_API_KEY']='synthetic-'+prefix
        self.values['RADARR_APP_HOLDING_PATH']='/arr-view/Movies_hold'
        self.values['SONARR_APP_HOLDING_PATH']='/arr-view/TV_hold'
        return server

    def test_public_due_worker_moves_one_and_delivers_only_its_arr_record(self):
        arr=self.arr();self.bind();result=self.due()
        self.assertEqual(len(result.outcome['completed']),1)
        self.assertEqual(len(result.outcome['arr_completed']),1)
        state,revision=self.store.load_with_revision()
        self.assertEqual(revision,6);self.assertNotIn(INTENTS_KEY,state)
        self.assertEqual(arr.puts,1);self.assertTrue(all(arr.intent_checks))
        self.assertFalse(any('series' in call[1] for call in arr.calls))
        self.assertEqual(arr.records['radarr'][0]['path'],'/arr-view/Movies_hold/Same (2020)')
        self.assertNotIn('never-export',json.dumps(state))
        self.assertEqual(require_sqlite_production_activation(settings=self.values)['DRY_RUN'],'false')
        calls=len(self.case.server.calls);self.step(self.case.fixture.slot+timedelta(seconds=1))
        self.assertEqual(len(self.case.server.calls),calls)
        self.assertEqual(self.source.read_bytes(),self.original)
        self.assertEqual(self.observer.report()['last_result'],'completed')

    def test_protection_change_stops_before_any_move_or_arr_put(self):
        arr=self.arr();self.bind();before=self.store.load_with_revision()
        self.case.server.mode='late-protect'
        result=self.due()
        self.assertEqual(result.outcome['completed'],())
        self.assertEqual(self.store.load_with_revision(),before)
        self.assertEqual(arr.puts,0)
        self.assertEqual(self.source.read_bytes(),self.original)

    def test_lost_arr_ack_keeps_latest_move_clock_and_blocks_replay(self):
        arr=self.arr();arr.mode='lost-ack';self.bind()
        with self.assertRaises(RuntimeError):self.due()
        state,revision=self.store.load_with_revision()
        self.assertEqual(revision,4)
        self.assertIn('Same (2020)',state['queued'])
        self.assertEqual(state[INTENTS_KEY]['kind'],'arr_sync')
        self.assertEqual(arr.puts,1)
        require_sqlite_read_authority(settings=self.values)
        calls=len(arr.calls)
        with self.assertRaises(RuntimeError):self.step(self.case.fixture.slot+timedelta(days=1))
        self.assertEqual(len(arr.calls),calls)
        self.assertEqual(self.observer.report()['last_result'],'failed')

    def test_actual_sigkill_after_rename_retains_intent_and_refuses_restart_dispatch(self):
        self.bind()
        code='''
import json,os,signal,sys
from datetime import datetime,timedelta
from app import sqlite_scheduled_routed_batch as batch
from app.sqlite_scheduled_production import production_cycle_step
from app.sqlite_scheduled_worker_cycle import ScheduledWorkerCycle
values=json.load(sys.stdin);slot=datetime.fromisoformat(values.pop('_fixture_slot'))
clock=datetime.fromisoformat(values.pop('_fixture_clock'))
original=batch.rename_directory_noreplace_at
def stop(*args):
    original(*args)
    os.kill(os.getpid(),signal.SIGKILL)
batch.rename_directory_noreplace_at=stop
cycle=ScheduledWorkerCycle()
for now in (slot-timedelta(hours=1),slot):
    production_cycle_step(cycle=cycle,settings=values,now=now,clock=lambda:clock)
'''
        values=dict(self.values,_fixture_slot=self.case.fixture.slot.isoformat(),_fixture_clock=NOW.isoformat())
        child=subprocess.run([sys.executable,'-B','-c',code],input=json.dumps(values),text=True,capture_output=True,timeout=30)
        self.assertEqual(child.returncode,-signal.SIGKILL)
        state,_=self.store.load_with_revision();self.assertIn(INTENTS_KEY,state)
        self.assertTrue(self.case.fixture.fixture.path(0,'holding').is_dir())
        require_sqlite_read_authority(settings=self.values)
        calls=len(self.case.server.calls)
        with self.assertRaises(RuntimeError):self.step(self.case.fixture.slot+timedelta(days=1))
        self.assertEqual(len(self.case.server.calls),calls)
        self.assertEqual(self.source.read_bytes(),self.original)

    def test_actual_entrypoint_keeps_api_available_after_restart_with_pending_intent(self):
        self.bind();self.due()
        state,revision=self.store.load_with_revision();state[INTENTS_KEY]={'fixture':'unresolved'}
        self.store.save_if_revision(state,revision);before=self.store.load_with_revision()
        with socket.socket() as reserve:
            reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
        token='disposable-live-api-token-0123456789'
        env=dict(os.environ,**self.values,WEB_PORT=str(port),WEB_SESSION_SECRET='disposable-live-session-secret',
                 INTEGRATION_API_TOKEN=token,INTEGRATION_API_TITLE_DETAILS='true')
        process=subprocess.Popen([sys.executable,'-B','-m','app.main'],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        def fetch(path,auth=True):
            request=urllib.request.Request(f'http://127.0.0.1:{port}'+path,headers={'Authorization':'Bearer '+token} if auth else {})
            try:
                with urllib.request.urlopen(request,timeout=1) as response:return response.status,response.read()
            except urllib.error.HTTPError as error:
                with error:return error.code,error.read()
        try:
            for _ in range(100):
                self.assertIsNone(process.poll())
                try:
                    if fetch('/login',False)[0]==200:break
                except (OSError,urllib.error.URLError):pass
                time.sleep(.05)
            else:self.fail('Live login did not become available')
            self.assertEqual(fetch('/api/v1/summary',False)[0],401)
            code,raw=fetch('/api/v1/summary');report=json.loads(raw)
            self.assertEqual(code,200);self.assertTrue(report['pending_operation_present'])
            self.assertEqual(report['execution_mode'],'scheduled_live_moves')
            self.assertFalse(report['media_actions_authorized'])
            self.assertFalse(report['permanent_deletion_authorized'])
            self.assertEqual(self.store.load_with_revision(),before)
            self.assertEqual(self.source.read_bytes(),self.original)
            process.send_signal(signal.SIGINT);out,err=process.communicate(timeout=5)
            self.assertEqual(process.returncode,0);self.assertNotIn(token,out+err)
        finally:
            if process.poll() is None:process.kill();process.communicate(timeout=5)


def main():
    if (not Path(binding.__file__).is_relative_to('/app/app') or build.PROFILE!=binding.PROFILE
            or build.SOURCE_REVISION!=os.environ['EXPECTED_RELEASE_REVISION']):
        raise RuntimeError('Actual immutable packaged live release required')
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(LiveReleaseTests))
    if not result.wasSuccessful() or result.testsRun!=5 or result.skipped:raise SystemExit(1)
    print(json.dumps({'status':'actual_live_release_fixture_verified','tests':result.testsRun,
                     'source_revision':build.SOURCE_REVISION,'fixture_only':True,'production_services_changed':False,
                     'permanent_deletion_authorized':False,'initial_maximum_actions':1}))


if __name__=='__main__':main()
