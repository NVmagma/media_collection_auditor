"""Disposable settings application faults; never production paths or services."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import unittest
from unittest.mock import patch

from app import sqlite_preview_activation as activation, sqlite_release_profile as build
from app import sqlite_preview_settings_apply as apply
from app.sqlite_preview_settings import request_settings,PENDING
from app.sqlite_lock import state_writer_lock
from app.state_store import GuardedSQLiteStateStore
from scripts.sqlite_preview_release_fixture import prepare_case


@unittest.skipUnless(sys.platform=='linux','Linux descriptor-bound settings application')
class SettingsApplyFixtureTests(unittest.TestCase):
    def setUp(self):
        self.case,self.source,self.control,self.saved,self.values=prepare_case()
        self.addCleanup(self.case.doCleanups)
        settings_dir=self.saved.parent/'settings';settings_dir.mkdir(mode=0o700)
        moved=settings_dir/'config.json';self.saved.rename(moved);self.saved=moved
        self.values['WEB_CONFIG_FILE']=str(self.saved)
        for key,value in (('PROFILE',activation.PROFILE),('SOURCE_REVISION','a'*40)):
            item=patch.object(build,key,value);item.start();self.addCleanup(item.stop)
        self.saved.write_text(json.dumps({'private_extension':{'clock':'keep-this'}}))
        activation.create_preview_binding(settings=self.values)
        self.before=(self.source.read_bytes(),(self.control/'state.db').read_bytes(),
            GuardedSQLiteStateStore(self.control/'state.db').load_with_revision())
        self.original=self.saved.read_bytes()
        self.binding=(self.control/activation.BINDING).read_bytes()
        self.pending=self.saved.parent/PENDING
        self.marker=self.control/activation.SETTINGS_MARKER
        self.request()

    def request(self,**changes):
        updated=json.loads(self.saved.read_bytes())
        updated.update(ENABLE_TV='false',HOLDING_DAYS='10',**changes)
        request_settings(config_path=self.saved,updated=updated,environment=self.values)
        self.digest=hashlib.sha256(self.pending.read_bytes()).hexdigest()

    def execute(self):
        return apply.apply_requested_settings(settings=self.values,request_sha256=self.digest)

    def restore(self):
        return apply.restore_previous_settings(settings=self.values,request_sha256=self.digest)

    def unchanged_tracking(self):
        self.assertEqual(self.before,(self.source.read_bytes(),(self.control/'state.db').read_bytes(),
            GuardedSQLiteStateStore(self.control/'state.db').load_with_revision()))

    def interrupt(self,phase):
        def stop(value):
            if value==phase:raise RuntimeError('fixture interruption')
        with patch.object(apply,'_boundary',stop),self.assertRaises(RuntimeError):self.execute()
        self.assertTrue(self.marker.exists())
        with self.assertRaises(RuntimeError):activation.validate_preview_activation(settings=self.values)
        self.unchanged_tracking()

    def test_application_preserves_database_clocks_unknowns_and_source(self):
        result=self.execute()
        self.assertEqual(result['status'],'settings_applied')
        values=activation.validate_preview_activation(settings=self.values)
        self.assertEqual(values['ENABLE_TV'],'false');self.assertEqual(values['HOLDING_DAYS'],'10')
        self.assertEqual(json.loads(self.saved.read_bytes())['private_extension'],{'clock':'keep-this'})
        self.assertFalse(self.marker.exists());self.assertFalse(self.pending.exists())
        self.unchanged_tracking()
        with self.assertRaises((RuntimeError,FileNotFoundError)):self.execute()
        self.unchanged_tracking()

    def test_source_scan_lock_blocks_before_any_intent(self):
        with state_writer_lock(self.source),self.assertRaises(RuntimeError):self.execute()
        self.assertFalse(self.marker.exists());self.assertEqual(self.saved.read_bytes(),self.original)
        self.unchanged_tracking()

    def test_stale_request_never_overwrites_new_active_settings(self):
        self.saved.write_text('{"HOLDING_DAYS":"12"}')
        with self.assertRaises(RuntimeError):self.execute()
        self.assertEqual(self.saved.read_text(),'{"HOLDING_DAYS":"12"}')
        self.assertFalse(self.marker.exists())

    def test_changed_request_digest_blocks_before_intent(self):
        self.pending.write_bytes(self.pending.read_bytes()+b' ')
        with self.assertRaises(RuntimeError):self.execute()
        self.assertFalse(self.marker.exists());self.assertEqual(self.saved.read_bytes(),self.original)

    def test_unsafe_request_never_enables_media_actions(self):
        request=json.loads(self.pending.read_bytes());request['requested_config']['DRY_RUN']='false'
        self.pending.write_text(json.dumps(request));self.digest=hashlib.sha256(self.pending.read_bytes()).hexdigest()
        with self.assertRaises(RuntimeError):self.execute()
        self.assertFalse(self.marker.exists());self.assertEqual(self.saved.read_bytes(),self.original)
        self.unchanged_tracking()

    def test_unknown_saved_fields_cannot_be_replaced(self):
        request=json.loads(self.pending.read_bytes());request['requested_config']['private_extension']={}
        self.pending.write_text(json.dumps(request));self.digest=hashlib.sha256(self.pending.read_bytes()).hexdigest()
        with self.assertRaises(RuntimeError):self.execute()
        self.assertFalse(self.marker.exists());self.unchanged_tracking()

    def test_each_interrupted_phase_requires_explicit_restoration(self):
        # Separate fixtures avoid adopting or overwriting a retained attempt.
        for phase in ('after_intent','after_config','after_binding','after_complete'):
            with self.subTest(phase=phase):
                case=SettingsApplyFixtureTests();case.setUp()
                try:
                    case.interrupt(phase)
                    with case.assertRaises(RuntimeError):case.execute()
                    case.assertEqual(case.restore()['status'],'previous_settings_restored')
                    case.assertEqual(case.saved.read_bytes(),case.original)
                    case.assertEqual((case.control/activation.BINDING).read_bytes(),case.binding)
                    activation.validate_preview_activation(settings=case.values);case.unchanged_tracking()
                finally:case.doCleanups()

    def test_identical_unrecognized_config_replacement_blocks_restoration(self):
        self.interrupt('after_config')
        duplicate=self.saved.with_suffix('.replacement');duplicate.write_bytes(self.saved.read_bytes())
        duplicate.replace(self.saved)
        with self.assertRaises(RuntimeError):self.restore()
        self.assertTrue(self.marker.exists());self.unchanged_tracking()

    def test_changed_newer_request_is_not_consumed(self):
        def change(phase):
            if phase=='after_config':self.pending.write_bytes(b'{"new_request":true}')
        with patch.object(apply,'_boundary',change),self.assertRaises(RuntimeError):self.execute()
        self.restore()
        self.assertEqual(self.pending.read_bytes(),b'{"new_request":true}');self.unchanged_tracking()

    def test_corrupt_journal_refuses_restoration_without_writes(self):
        self.interrupt('after_config')
        tx=self.control.parent/('settings-apply-'+self.digest)
        (tx/'old-config.json').write_text('changed')
        active=self.saved.read_bytes()
        with self.assertRaises(RuntimeError):self.restore()
        self.assertEqual(self.saved.read_bytes(),active);self.assertTrue(self.marker.exists())

    def test_interrupted_restoration_can_be_resumed_explicitly(self):
        self.interrupt('after_binding')
        def stop(phase):
            if phase=='restored_config':raise RuntimeError('restore interruption')
        with patch.object(apply,'_boundary',stop),self.assertRaises(RuntimeError):self.restore()
        self.assertTrue(self.marker.exists());self.unchanged_tracking()
        self.assertEqual(self.restore()['status'],'previous_settings_restored')
        activation.validate_preview_activation(settings=self.values);self.unchanged_tracking()

    def test_old_prepared_scan_is_rejected_after_settings_application(self):
        from app.sqlite_scheduled_production import _run_bound_production_slot
        from scripts.sqlite_scheduled_routed_slot_fixture import NOW
        old=activation.validate_preview_activation(settings=self.values)
        self.execute()
        with self.assertRaisesRegex(RuntimeError,'changed before scan lock'):
            _run_bound_production_slot(settings=old,scheduled_at=self.case.fixture.slot,
                now=self.case.fixture.slot,clock=lambda:NOW)
        self.assertEqual(self.case.server.calls,[]);self.unchanged_tracking()

    def test_replaced_settings_parent_is_not_written_or_adopted(self):
        import shutil
        original_parent=self.saved.parent
        retained=original_parent.with_name('retained-settings')
        def replace(phase):
            if phase=='after_intent':
                original_parent.rename(retained);original_parent.mkdir(mode=0o700)
                self.saved.write_text('replacement-tree-must-not-change')
        try:
            with patch.object(apply,'_boundary',replace),self.assertRaises(RuntimeError):self.execute()
            self.assertEqual(self.saved.read_text(),'replacement-tree-must-not-change')
            self.assertEqual((retained/self.saved.name).read_bytes(),self.original)
            self.assertTrue(self.marker.exists());self.unchanged_tracking()
        finally:
            if retained.exists():
                shutil.rmtree(original_parent);retained.rename(original_parent)

    def test_replaced_database_blocks_restoration_before_configuration_write(self):
        self.interrupt('after_config')
        database=self.control/'state.db'
        changed=self.control/'replacement.db';changed.write_bytes(database.read_bytes());changed.replace(database)
        active=self.saved.read_bytes()
        with self.assertRaises(RuntimeError):self.restore()
        self.assertEqual(self.saved.read_bytes(),active);self.assertTrue(self.marker.exists())

    def test_identical_transaction_directory_replacement_is_not_adopted(self):
        import shutil
        self.interrupt('after_config')
        tx=self.control.parent/('settings-apply-'+self.digest)
        retained=tx.with_name('retained-transaction')
        tx.rename(retained);shutil.copytree(retained,tx)
        active=self.saved.read_bytes()
        with self.assertRaises(RuntimeError):self.restore()
        self.assertEqual(self.saved.read_bytes(),active);self.assertTrue(self.marker.exists())
        self.unchanged_tracking()

    def test_actual_sigkill_after_config_keeps_interface_gate_paused_and_tracking(self):
        code='''
import json,os,signal,sys
from app import sqlite_preview_settings_apply as m,sqlite_release_profile as b
b.PROFILE='scheduled-preview-v1';b.SOURCE_REVISION='a'*40
values=json.loads(sys.stdin.readline());digest=sys.stdin.readline().strip()
def kill(phase):
    if phase=='after_config':os.kill(os.getpid(),signal.SIGKILL)
m._boundary=kill
m.apply_requested_settings(settings=values,request_sha256=digest)
'''
        result=subprocess.run([sys.executable,'-B','-c',code],input=json.dumps(self.values)+'\n'+self.digest+'\n',
            text=True,capture_output=True,timeout=20)
        self.assertEqual(result.returncode,-signal.SIGKILL,result.stderr)
        self.assertTrue(self.marker.exists());self.unchanged_tracking()
        with self.assertRaises(RuntimeError):activation.validate_preview_activation(settings=self.values)
        self.restore();activation.validate_preview_activation(settings=self.values);self.unchanged_tracking()


def actual_image_acceptance():
    """Real web process, signed admin session, application, crash and recovery."""
    import socket,time
    from datetime import datetime,timedelta,timezone
    import requests
    from app.config_store import KEYS,SECRETS
    if (build.PROFILE!=activation.PROFILE or build.SOURCE_REVISION!=os.environ['EXPECTED_RELEASE_REVISION']
            or not Path(apply.__file__).is_relative_to('/app/app')):
        raise RuntimeError('Actual immutable settings preview image required')
    case,source,control,saved,values=prepare_case()
    process=None
    try:
        # Keep scheduled work outside the fixture lifetime; only explicit UI
        # settings requests are exercised here.
        future=datetime.now(timezone.utc)+timedelta(hours=4)
        values.update(SQLITE_DAILY_RUN_TIME=future.strftime('%H:%M'),SQLITE_DAILY_RUN_TIMEZONE='UTC')
        activation.create_preview_binding(settings=values)
        original=(source.read_bytes(),(control/'state.db').read_bytes())
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        base='http://127.0.0.1:'+str(port)
        token='fixture-settings-transport-token-0123456789'
        env={**os.environ,**values,'WEB_PORT':str(port),'WEB_SESSION_SECRET':'fixture-settings-session-key',
            'WEB_ADMIN_USER':'fixture-admin','WEB_ADMIN_PASSWORD':'fixture-password','INTEGRATION_API_TOKEN':token}
        session=requests.Session();session.trust_env=False
        def start(crash=False):
            if crash:
                code="import os,signal,runpy; from app import sqlite_preview_settings_apply as m; m._boundary=lambda phase: os.kill(os.getpid(),signal.SIGKILL) if phase=='after_config' else None; runpy.run_module('app.main',run_name='__main__')"
                command=[sys.executable,'-B','-c',code]
            else:command=[sys.executable,'-B','-m','app.main']
            child=subprocess.Popen(command,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            for _ in range(100):
                if child.poll() is not None:
                    child.communicate(timeout=5);raise RuntimeError('Fixture server stopped before readiness')
                try:
                    if session.get(base+'/health',timeout=1).status_code==200:return child
                except requests.RequestException:pass
                time.sleep(.05)
            child.kill();child.communicate(timeout=5);raise RuntimeError('Fixture readiness expired')
        def stop():
            nonlocal process
            process.send_signal(signal.SIGINT);out,err=process.communicate(timeout=10)
            assert process.returncode==0 and token not in out+err
            process=None
        def post(route,data):
            return session.post(base+route,data=data,headers={'Origin':base},allow_redirects=False,timeout=10)
        def request_changes(days):
            current=json.loads(saved.read_bytes())
            form={key:('' if key in SECRETS else current.get(key,values.get(key,''))) for key in KEYS}
            form.update(ENABLE_TV='false',HOLDING_DAYS=days)
            assert post('/settings',form).status_code==302
            digest=hashlib.sha256((saved.parent/PENDING).read_bytes()).hexdigest()
            return {'request_sha256':digest}
        def tracking_unchanged():
            assert (source.read_bytes(),(control/'state.db').read_bytes())==original
        process=start()
        assert post('/login',{'username':'fixture-admin','password':'fixture-password'}).status_code==302
        first=request_changes('10')
        assert post('/settings/apply',first).status_code==302
        assert json.loads(saved.read_bytes())['HOLDING_DAYS']=='10'
        active=saved.read_bytes();tracking_unchanged()
        second=request_changes('12')
        stop();process=start(crash=True)
        try:post('/settings/apply',second)
        except requests.RequestException:pass
        process.communicate(timeout=10)
        assert process.returncode==-signal.SIGKILL
        process=None
        assert (control/activation.SETTINGS_MARKER).exists();tracking_unchanged()
        process=start()
        page=session.get(base+'/settings',timeout=5)
        assert page.status_code==200 and 'Restore Previous Settings' in page.text
        assert session.get(base+'/api/v1/summary',timeout=5).status_code==401
        assert session.get(base+'/api/v1/summary',headers={'Authorization':'Bearer '+token},timeout=5).status_code==503
        restored=post('/settings/restore',second)
        assert restored.status_code==302 and 'restored=1' in restored.headers['Location']
        assert saved.read_bytes()==active;tracking_unchanged()
        assert session.get(base+'/api/v1/summary',headers={'Authorization':'Bearer '+token},timeout=5).status_code==200
        assert 'resubmit' in session.get(base+'/settings',timeout=5).text.lower() or 'save a new request' in session.get(base+'/settings',timeout=5).text
        stop();session.close()
        print(json.dumps({'status':'actual_settings_application_verified','source_revision':build.SOURCE_REVISION,
            'authenticated_apply_verified':True,'controller_sigkill_verified':True,'restart_ui_available':True,
            'explicit_restore_verified':True,'tracking_bytes_unchanged':True,'fixture_only':True,
            'media_actions_authorized':False,'production_services_changed':False}))
    finally:
        if process is not None and process.poll() is None:
            process.kill();process.communicate(timeout=5)
        case.doCleanups()


def main():
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SettingsApplyFixtureTests))
    if not result.wasSuccessful() or result.skipped:raise SystemExit(1)
    if '--actual-image' in sys.argv:actual_image_acceptance()
    print(json.dumps({'status':'preview_settings_apply_fixture_verified','tests':result.testsRun,
        'fixture_only':True,'media_actions_authorized':False,'service_changes_performed':False}))

if __name__=='__main__':main()
