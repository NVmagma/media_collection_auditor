"""Start the packaged app with empty appdata, then test setup, login, and restart without media mounts."""
import http.cookiejar
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE='http://127.0.0.1:8080'
root=Path('/app/logs')
assert not any(root.iterdir()), 'New empty disposable appdata required'
env={key:value for key,value in os.environ.items() if key not in ('WEB_ADMIN_PASSWORD','WEB_ADMIN_USER','WEB_SESSION_SECRET','INTEGRATION_API_TOKEN')}


def start():
    proc=subprocess.Popen([sys.executable,'-B','-m','app.main'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            if urllib.request.urlopen(BASE+'/health',timeout=1).status==200: return proc
        except (OSError,urllib.error.URLError): pass
        if proc.poll() is not None: raise RuntimeError('Entrypoint exited during first-run test')
        time.sleep(.1)
    proc.terminate();proc.wait(timeout=10)
    raise RuntimeError('WebUI startup timed out')


def post(path,data,opener):
    return opener.open(urllib.request.Request(BASE+path,data=urllib.parse.urlencode(data).encode(),headers={'Origin':BASE}),timeout=10)


proc=start()
try:
    opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    assert opener.open(BASE+'/login').url.endswith('/setup')
    token=(root/'setup-token').read_text().strip()
    assert 'a-fixture-password' not in (root/'auditor_config.json').read_text()
    post('/setup',dict(code=token,username='fixture-admin',password='a-fixture-password'),opener)
    post('/login',dict(username='fixture-admin',password='a-fixture-password'),opener)
    response=opener.open(BASE+'/settings')
    assert response.status==200 and b'Apply Requested Settings' in response.read()
    post('/settings',dict(settings_action='apply', INTEGRATION_API_TOKEN='synthetic-'+'X'*40,
                          INTEGRATION_API_TITLE_DETAILS='true'),opener)
    request=urllib.request.Request(BASE+'/api/v1/readiness',headers={'Authorization':'Bearer synthetic-'+'X'*40})
    readiness=json.load(opener.open(request))
    assert readiness['title_details_enabled'] is True
    post('/settings',dict(settings_action='apply',disable_integration_api='yes'),opener)
    try: opener.open(request)
    except urllib.error.HTTPError as error: assert error.code==404
    else: raise AssertionError('Revoked integration token still accepted')
    saved=json.loads((root/'auditor_config.json').read_text())
    assert saved['DRY_RUN']=='true' and saved['ALLOW_PERMANENT_DELETE']=='false'
    assert not (root/'setup-token').exists()
    before=(root/'auditor_state.json').read_bytes()
finally:
    proc.send_signal(__import__('signal').SIGINT);proc.wait(timeout=10)
proc=start()
try:
    assert opener.open(BASE+'/settings').status==200, 'Generated session key must survive restart'
    assert (root/'auditor_state.json').read_bytes()==before
    assert b'a-fixture-password' not in (root/'auditor_config.json').read_bytes()
finally:
    proc.send_signal(__import__('signal').SIGINT);proc.wait(timeout=10)
print(json.dumps({'status':'unraid_template_onboarding_verified','fixture_only':True,'production_services_changed':False,'media_mounted':False,'environment_credentials_required':False,'account_hashed':True,'restart_verified':True}))
