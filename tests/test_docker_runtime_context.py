"""Check that the files copied into the image work without modules from the checkout."""
import json,os,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def context(tmp_path):
    shutil.copytree(ROOT/'app',tmp_path/'app')
    return tmp_path

def probe(runtime,raw):
    source=runtime/'state.json';source.write_text(raw)
    env={**os.environ,'PYTHONPATH':str(runtime)+':'+str(runtime/'app'),'STATE_FILE':str(source),
        'WEB_SESSION_SECRET':'synthetic-runtime-secret','INTEGRATION_API_TOKEN':'synthetic-runtime-integration-token',
        'AUDITOR_STATE_BACKEND':'json','AUDITOR_WORKER_MODE':'json_serialized'}
    code='''import web
try: state=web.load_state()
except RuntimeError: print('TRACKING_ERROR_VISIBLE')
else:
 assert state['first_seen']['Example']=='2024-01-01T00:00:00'
 response=web.app.test_client().get('/api/v1/summary',headers={'Authorization':'Bearer synthetic-runtime-integration-token'})
 assert response.status_code==200 and response.json['storage_authority']=='json'
 print('RUNTIME_OK')'''
    return subprocess.run([sys.executable,'-B','-c',code],cwd=runtime,env=env,capture_output=True,text=True,timeout=30)

def test_runtime_can_import_and_read_state(tmp_path):
    result=probe(context(tmp_path),json.dumps({'first_seen':{'Example':'2024-01-01T00:00:00'}}))
    assert result.returncode==0,result.stderr
    assert 'RUNTIME_OK' in result.stdout

def test_corrupt_tracking_is_visible(tmp_path):
    result=probe(context(tmp_path),'{"first_seen":[]}')
    assert result.returncode==0,result.stderr
    assert 'TRACKING_ERROR_VISIBLE' in result.stdout

def test_missing_runtime_dependency_is_detected(tmp_path):
    runtime=context(tmp_path);(runtime/'app/json_validation.py').unlink()
    result=probe(runtime,'{}')
    assert result.returncode!=0 and 'json_validation' in result.stderr
