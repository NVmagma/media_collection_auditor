"""Packaged dashboard acceptance using new disposable folders and SQLite only."""
from datetime import datetime,timedelta,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time


def actual_image_acceptance():
    from app import sqlite_preview_activation as activation,sqlite_release_profile as build
    from app.sqlite_release_preparation import prepare_release_state
    from app.sqlite_state import SECTIONS
    from scripts.sqlite_preview_release_fixture import prepare_case
    import requests
    if (build.PROFILE!=activation.PROFILE or build.SOURCE_REVISION!=os.environ.get('EXPECTED_RELEASE_REVISION')
            or not Path(activation.__file__).is_relative_to('/app/app')):
        raise RuntimeError('Actual immutable preview image required')
    case,_,_,saved,values=prepare_case()
    process=None
    try:
        state={section:{} for section in SECTIONS}
        state['fixture_extension']={'private':'never-render-this-extension'}
        root=case.fixture.root
        for library,total,tracked in (('Movies',513,454),('TV',69,66)):
            binding=next(item for item in case.fixture.config.libraries if item.name==library)
            roots=dict(binding.roots)
            for index in range(total):
                title='Same (2020)' if index==0 else 'Fixture '+library+' '+str(index)
                directory=Path(roots['Waiting'])/title
                directory.mkdir(exist_ok=True)
                if index<tracked:state['first_seen'][('TV/' if library=='TV' else '')+title]='2026-10-15T11:30:00'
            if library=='Movies':
                for stage,section,count in (('Holding','queued',4),('Keep','keep_seen',13)):
                    for index in range(count):
                        title='Fixture '+stage+' '+str(index)
                        (Path(roots[stage])/title).mkdir()
                        state[section][title]='2026-10-15T11:30:00'
        for index in range(2):state['first_seen']['TV/Unmatched fixture '+str(index)]='2026-10-15T11:30:00'
        source=root/'dashboard-source.json';control=root/'dashboard-control'
        source.write_text(json.dumps(state))
        prepare_release_state(source=source,control_directory=control,
            expected_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
        future=datetime.now(timezone.utc)+timedelta(hours=4)
        values.update(STATE_FILE=str(source),SQLITE_STATE_FILE=str(control/'state.db'),
            SQLITE_DAILY_RUN_TIME=future.strftime('%H:%M'),SQLITE_DAILY_RUN_TIMEZONE='UTC')
        activation.create_preview_binding(settings=values)
        before=(source.read_bytes(),(control/'state.db').read_bytes(),saved.read_bytes())
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        base='http://127.0.0.1:'+str(port)
        env={**os.environ,**values,'WEB_PORT':str(port),'WEB_SESSION_SECRET':'fixture-dashboard-session',
            'WEB_ADMIN_USER':'fixture-admin','WEB_ADMIN_PASSWORD':'fixture-password'}
        session=requests.Session();session.trust_env=False
        process=subprocess.Popen([sys.executable,'-B','-m','app.main'],env=env,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        for _ in range(100):
            if process.poll() is not None:raise RuntimeError('Fixture server stopped')
            try:
                if session.get(base+'/health',timeout=1).status_code==200:break
            except requests.RequestException:pass
            time.sleep(.05)
        else:raise RuntimeError('Fixture server readiness expired')
        response=session.post(base+'/login',data={'username':'fixture-admin','password':'fixture-password'},
            headers={'Origin':base},allow_redirects=False,timeout=10)
        assert response.status_code==302
        response=session.get(base+'/',timeout=30)
        assert response.status_code==200
        assert 'id="clock-coverage"' not in response.text
        response=session.get(base+'/review',timeout=30)
        assert response.status_code==200
        page=response.text
        assert '62 folders without a stage date' in page
        assert '2 records without a matching stage folder' in page
        assert re.search(r'<td>Movies</td><td>Waiting.*?<td>513</td>\s*<td>59</td>',page,re.S)
        assert re.search(r'<td>TV</td><td>Waiting.*?<td>69</td>\s*<td>3</td>',page,re.S)
        assert 'Not yet tracked' in page and '10/15/2026 11:30' in page
        assert 'never-render-this-extension' not in page
        assert (source.read_bytes(),(control/'state.db').read_bytes(),saved.read_bytes())==before
        process.send_signal(signal.SIGINT);process.communicate(timeout=10)
        assert process.returncode==0
        process=None;session.close()
        print(json.dumps({'status':'actual_dashboard_clock_coverage_verified','source_revision':build.SOURCE_REVISION,
            'missing_dates':62,'records_without_stage_folder':2,'tracking_bytes_unchanged':True,
            'authenticated_dashboard_verified':True,'fixture_only':True,'freshness_verified':False,
            'media_actions_authorized':False,'production_services_changed':False}))
    finally:
        if process is not None and process.poll() is None:
            process.kill();process.communicate(timeout=5)
        case.doCleanups()

if __name__=='__main__':actual_image_acceptance()
