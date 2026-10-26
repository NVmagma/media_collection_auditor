"""Fresh preview acceptance on explicitly marked disposable Docker volume binds."""
from contextlib import closing
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from time import monotonic, sleep
import unittest
from unittest.mock import patch

from app.sqlite_preview_activation import validate_preview_activation
from app.state_store import GuardedSQLiteStateStore
from scripts import sqlite_preview_fresh as fresh
from scripts import sqlite_preview_cutover_fixture as packet_fixture
from scripts.sqlite_preview_cutover_fixture import SECRET
from scripts.sqlite_preview_release_request import fingerprint
from scripts.sqlite_preview_service import Docker, UnixConnection, preview_payload, verify_http_health
from app.sqlite_release_recovery import _encode
from app.sqlite_json import parse_unique_json

REFERENCE = 'ghcr.io/nvmagma/media_collection_auditor@sha256:'+'9'*64


class FixtureJellyfin(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        payload=json.dumps([{'Id':'fixture-user'}] if self.path=='/Users'
            else {'TotalRecordCount':0,'Items':[]}).encode()
        self.send_response(200); self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(payload))); self.end_headers(); self.wfile.write(payload)


class FixtureDocker(Docker):
    def request(self, method, route, payload=None, statuses=(200,)):
        if method != 'POST' or not route.startswith('/containers/create?'):
            return super().request(method,route,payload,statuses)
        # Synthetic fixture only: surface the one-shot create rejection without
        # retrying or logging private production payloads in the service client.
        self.check()
        with closing(UnixConnection(self.endpoint)) as connection:
            connection.request(method,self.prefix+route,body=_encode(payload),headers={'Content-Type':'application/json'})
            response=connection.getresponse(); raw=response.read(65537)
            self.check()
            if response.status not in statuses or len(raw)>65536:
                raise RuntimeError('Fixture create rejected: '+str(response.status)+' '+raw[:1000].decode(errors='replace'))
            return parse_unique_json(raw)


def identity(path):
    info = Path(path).stat(); return info.st_dev, info.st_ino


def assert_fixture():
    root = os.environ.get('HOST_FIXTURE_ROOT','')
    if not re.fullmatch('/var/lib/docker/volumes/auditor-service-fixture-[0-9a-f]{16}/_data',root):
        raise RuntimeError('Explicit new local fixture volume required')
    for name,path in (('packet','/packet'),('logs','/app/logs'),('control','/sqlite-control')):
        if identity('/lab/'+name) != identity(path): raise RuntimeError('Disposable bind identity mismatch')


class FreshPreviewTests(unittest.TestCase):
    def setUp(self):
        assert_fixture()
        for directory in ('/packet','/app/logs','/sqlite-control'):
            for item in Path(directory).iterdir():
                if item.is_dir() and not item.is_symlink(): shutil.rmtree(item)
                else: item.unlink()
        self.case = packet_fixture.PreviewCutoverFixtureTests(); self.case.setUp(); self.addCleanup(self.case.doCleanups)
        self.case.root = Path('/packet')
        # Docker requires slave/shared propagation for binds under its own
        # private volume root; this is fixture layout, not a Tower change.
        for mount in self.case.old[0]['Mounts']: mount['Propagation']='rslave'
        self.case.old[0]['HostConfig']['PortBindings'] = {'8080/tcp':[{'HostIp':'','HostPort':'8089'}]}
        # Actual dashboard/manual scans may collect signals: direct them only to
        # this private fixture server, never an external Jellyfin or DNS origin.
        server=ThreadingHTTPServer(('0.0.0.0',0),FixtureJellyfin)
        worker=Thread(target=lambda:server.serve_forever(poll_interval=.01),daemon=True); worker.start()
        self.addCleanup(lambda:(server.shutdown(),server.server_close(),worker.join(timeout=2)))
        address=socket.gethostbyname(socket.gethostname())
        self.case.old[0]['Config']['Env']=[item for item in self.case.old[0]['Config']['Env']
            if not item.startswith('JELLYFIN_HOST_URL=')]
        self.case.old[0]['Config']['Env'].append('JELLYFIN_HOST_URL=http://'+address+':'+str(server.server_port))
        self.case.state['queued']['TV/Fixture Holding'] = '2024-03-01T00:00:00'
        self.case.old[0]['Config']['Env'] += ['INTEGRATION_API_TITLE_DETAILS=true','INTEGRATION_API_MEDIA=false', 'WEB_SESSION_SECRET=synthetic-manual-preview-session-key']
        self.case.inputs()
        (self.case.root/'original-template.xml').write_text('<Container><Name>media_collection_auditor</Name></Container>')
        self.report = self.case.write()
        self.before = {p.name:p.read_bytes() for p in self.case.root.iterdir()}
        self.kwargs = dict(packet=self.case.root,packet_identity=identity(self.case.root),
            expected_fingerprint=fingerprint(self.report), logs=Path('/app/logs'), logs_identity=identity('/app/logs'),
            control=Path('/sqlite-control'),control_identity=identity('/sqlite-control'),
            host_logs=os.environ['HOST_FIXTURE_ROOT']+'/logs',host_control=os.environ['HOST_FIXTURE_ROOT']+'/control',
            image_id=os.environ['EXPECTED_PREVIEW_IMAGE'],reference=REFERENCE)

    def unchanged(self):
        self.assertEqual({p.name:p.read_bytes() for p in self.case.root.iterdir()},self.before)

    def test_fresh_sqlite_actual_frontend_and_authenticated_api(self):
        result = fresh.prepare(**self.kwargs)
        self.assertFalse(result['old_tracking_imported']); self.unchanged()
        state,revision = GuardedSQLiteStateStore('/sqlite-control/release/state.db').load_with_revision()
        self.assertEqual(revision,0); self.assertTrue(all(not value for value in state.values()))
        self.verify_running_preview()

    def verify_running_preview(self, expected_tv=0):
        env = dict(line.split('=',1) for line in Path('/app/logs/runtime.env').read_text().splitlines())
        self.assertEqual(env['INTEGRATION_API_TOKEN'],SECRET)
        validate_preview_activation(settings=env)
        xml = Path('/app/logs/fresh-template.xml').read_text()
        self.assertIn('/sqlite-control',xml); self.assertIn('Mode="ro,slave"',xml)
        raw = FixtureDocker(endpoint='/docker-engine.sock',expected_daemon=os.environ['EXPECTED_DAEMON_ID'])
        original = self.case.old[0]
        for mount in original['Mounts']:
            mount['Source'] = os.environ['HOST_FIXTURE_ROOT']+('/media' if mount['Destination']=='/media' else '/logs')
        original['HostConfig']['PortBindings'] = {}
        image = raw.image(self.kwargs['image_id'])
        payload = preview_payload(captured=original,image=image,env=env,
            control_host=self.kwargs['host_control'],reference=self.kwargs['image_id'],request_id='8'*64)
        name = 'auditor-fresh-fixture-'+os.urandom(8).hex()
        container = raw.create(name,payload)
        try:
            raw.start(container)
            verify_http_health(engine=raw,identity=container,env=env)
            observed = raw.inspect(container)
            address = observed['NetworkSettings']['Networks']['bridge']['IPAddress']
            with closing(http.client.HTTPConnection(address,8080,timeout=5)) as connection:
                connection.request('GET','/login')
                response = connection.getresponse()
                self.assertEqual(response.status,200)
                self.assertIn(b'<html',response.read().lower())
            self.assertEqual(observed['Config']['Labels']['net.unraid.docker.webui'],'http://[IP]:[PORT:8080]/')
            with closing(http.client.HTTPConnection(address,8080,timeout=5)) as connection:
                connection.request('GET','/')
                response=connection.getresponse()
                self.assertEqual(response.status,302)
                self.assertEqual(response.getheader('Location'),'/login')
                response.read()
            with closing(http.client.HTTPConnection(address,8080,timeout=5)) as connection:
                connection.request('GET','/api/v1/titles/leaving-soon?library=TV',
                    headers={'Authorization':'Bearer '+env['INTEGRATION_API_TOKEN']})
                response=connection.getresponse(); report=json.loads(response.read())
                self.assertEqual(response.status,200)
                self.assertEqual(report['library_filter'],'TV')
                self.assertEqual(report['total_records'],expected_tv)
                self.assertTrue(all(item['library']=='TV' for item in report['items']))
                if expected_tv: self.assertEqual(report['items'][0]['since'],'2024-03-01T00:00:00')
            # The real dashboard session, POST route and service wake must compose.
            # This key/cookie belongs only to this newly created fixture instance.
            from flask import Flask
            from flask.sessions import SecureCookieSessionInterface
            client_app=Flask('manual-preview-fixture'); client_app.secret_key=env['WEB_SESSION_SECRET']
            cookie=SecureCookieSessionInterface().get_signing_serializer(client_app).dumps({'provider':'local'})
            snapshot_before=GuardedSQLiteStateStore('/sqlite-control/release/state.db').load_with_revision()
            json_before=Path('/app/logs/auditor_state.json').read_bytes()
            with closing(http.client.HTTPConnection(address,8080,timeout=5)) as connection:
                connection.request('GET','/',headers={'Cookie':'session='+cookie})
                response=connection.getresponse(); page=response.read()
                self.assertEqual(response.status,200)
                self.assertIn(b'Run Preview Now',page)
            with closing(http.client.HTTPConnection(address,8080,timeout=5)) as connection:
                connection.request('POST','/api/run-now',headers={'Cookie':'session='+cookie,
                    'Origin':'http://'+address+':8080'})
                response=connection.getresponse(); response.read()
                self.assertEqual(response.status,202)
            deadline=monotonic()+15
            while monotonic()<deadline:
                with closing(http.client.HTTPConnection(address,8080,timeout=5)) as connection:
                    connection.request('GET','/api/v1/audit-status',
                        headers={'Authorization':'Bearer '+env['INTEGRATION_API_TOKEN']})
                    response=connection.getresponse(); audit=json.loads(response.read())
                if audit.get('last_trigger')=='manual' and audit.get('last_result') is not None: break
                sleep(.1)
            self.assertEqual(audit.get('last_trigger'),'manual')
            self.assertEqual(audit.get('last_result'),'completed')
            self.assertTrue(audit.get('dry_run')); self.assertEqual(audit.get('moves_completed'),0)
            self.assertFalse(audit.get('media_actions_authorized'))
            self.assertEqual(GuardedSQLiteStateStore('/sqlite-control/release/state.db').load_with_revision(),snapshot_before)
            self.assertEqual(Path('/app/logs/auditor_state.json').read_bytes(),json_before)
            self.assertFalse(Path('/sqlite-control/release/.sqlite_scheduled_slots').exists())
            self.assertFalse(next(m['RW'] for m in observed['Mounts'] if m['Destination']=='/media'))
            self.assertTrue(observed['HostConfig']['ReadonlyRootfs'])
            self.unchanged()
        finally:
            raw.request('DELETE','/containers/'+container+'?force=1&v=0',statuses=(204,))

    def test_restore_previous_snapshot_keeps_all_clocks_extensions_and_tv_records(self):
        state=json.loads(self.before['source-observed.json'])
        result=fresh.prepare(**self.kwargs,tracking_mode='restore-previous')
        self.assertTrue(result['old_tracking_imported'])
        actual,revision=GuardedSQLiteStateStore('/sqlite-control/release/state.db').load_with_revision()
        self.assertEqual(actual,state); self.assertEqual(revision,0)
        self.assertEqual(actual['keep_seen']['TV/Fixture Show'],'2024-02-01T00:00:00')
        self.assertEqual(actual['unknown'],state['unknown'])
        self.unchanged()
        self.verify_running_preview(expected_tv=1)

    def test_occupied_logs_never_overwritten(self):
        Path('/app/logs/retained').write_bytes(b'keep')
        with self.assertRaises(RuntimeError): fresh.prepare(**self.kwargs)
        self.assertEqual(Path('/app/logs/retained').read_bytes(),b'keep')
        self.assertEqual(list(Path('/sqlite-control').iterdir()),[]); self.unchanged()

    def test_occupied_control_never_overwritten(self):
        Path('/sqlite-control/retained').write_bytes(b'keep')
        with self.assertRaises(RuntimeError): fresh.prepare(**self.kwargs)
        self.assertEqual(Path('/sqlite-control/retained').read_bytes(),b'keep')
        self.assertEqual(list(Path('/app/logs').iterdir()),[]); self.unchanged()

    def test_wrong_settings_selection_never_writes(self):
        with self.assertRaises(RuntimeError): fresh.prepare(**{**self.kwargs,'expected_fingerprint':'0'*64})
        self.assertEqual(list(Path('/app/logs').iterdir()),[]); self.unchanged()

    def test_changed_private_input_never_writes(self):
        Path('/packet/original-config.json').write_text('{}')
        with self.assertRaises(RuntimeError): fresh.prepare(**self.kwargs)
        self.assertEqual(list(Path('/app/logs').iterdir()),[])

    def test_changed_generated_environment_never_writes(self):
        with Path('/packet/preview.env').open('ab') as file: file.write(b'DRY_RUN=false\n')
        with self.assertRaises(RuntimeError): fresh.prepare(**self.kwargs)
        self.assertEqual(list(Path('/app/logs').iterdir()),[])

    def test_partial_preparation_is_retained_and_not_replayed(self):
        with patch.object(fresh,'stage_preview',side_effect=RuntimeError('fixture interruption')):
            with self.assertRaises(RuntimeError): fresh.prepare(**self.kwargs)
        before = {p.name:p.read_bytes() for p in Path('/app/logs').iterdir()}
        with self.assertRaises(RuntimeError): fresh.prepare(**self.kwargs)
        self.assertEqual({p.name:p.read_bytes() for p in Path('/app/logs').iterdir()},before); self.unchanged()

    def test_unapproved_repository_never_writes(self):
        with self.assertRaises(RuntimeError): fresh.prepare(**{**self.kwargs,'reference':'elsewhere.invalid:latest'})
        self.assertEqual(list(Path('/app/logs').iterdir()),[]); self.unchanged()


if __name__ == '__main__':
    unittest.main(verbosity=2)
