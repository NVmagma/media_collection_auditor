#!/usr/bin/env python3
"""Disposable loopback HTTP fixture; no production state or external requests."""
import http.client
import json
import multiprocessing
import os
from pathlib import Path
import secrets
import sys
import tempfile


class FixtureFailure(RuntimeError):
    """A redacted fixture failure, never a server response or credential dump."""


def _require(condition, reason='fixture_assertion_failed'):
    if not condition:
        raise FixtureFailure(reason)


def _serve_fixture(directory, token, ready):
    server = None
    try:
        root = Path(__file__).resolve().parents[1]
        sys.path[:0] = [str(root / 'app'), str(root)]
        os.environ['STATE_FILE'] = str(Path(directory) / 'state.json')
        os.environ['WEB_CONFIG_FILE'] = str(Path(directory) / 'config.json')
        os.environ['ACTION_LOG_FILE'] = str(Path(directory) / 'actions.jsonl')
        os.environ['EXPERIMENTAL_SQLITE_RECOVERY_VIEW'] = 'false'
        os.environ['AUDIT_HISTORY_FILE'] = str(Path(directory) / 'history.jsonl')
        os.environ['WEB_SESSION_SECRET'] = secrets.token_urlsafe(32)
        os.environ['INTEGRATION_API_TOKEN'] = token
        import requests

        def forbidden(*args, **kwargs):
            raise FixtureFailure('external_action_forbidden')

        requests.sessions.Session.request = forbidden
        import socket
        socket.getfqdn = forbidden
        socket.gethostbyaddr = forbidden
        import web
        from socketserver import TCPServer
        from wsgiref.simple_server import WSGIServer, WSGIRequestHandler

        # Even an authorization regression must not execute a real action.
        web.request_run = forbidden
        web.rescue_title = forbidden
        web.check_connection = forbidden
        web.app.config.update(DEBUG=False, TESTING=False)

        class QuietHandler(WSGIRequestHandler):
            def log_message(self, *args, **kwargs):
                pass

        class LoopbackServer(WSGIServer):
            def server_bind(self):
                # HTTPServer.server_bind calls getfqdn, which can invoke DNS.
                # This fixture needs only literal loopback and a fixed name.
                TCPServer.server_bind(self)
                self.server_name = 'localhost'
                self.server_port = self.server_address[1]
                self.setup_environ()

        server = LoopbackServer(('127.0.0.1', 0), QuietHandler)
        server.set_app(web.app)
        ready.send({'status': 'ready', 'port': server.server_port})
        ready.close()
        server.serve_forever(poll_interval=0.1)
    except (Exception, SystemExit):
        try:
            ready.send({'status': 'unavailable'})
        except (OSError, ValueError):
            pass
    finally:
        ready.close()
        if server is not None:
            server.server_close()


def _request(port, path, *, token=None, method='GET'):
    # Literal loopback + direct HTTPConnection: no DNS, proxy, redirect or retry.
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
    try:
        headers = {} if token is None else {'Authorization': 'Bearer ' + token}
        connection.request(method, path, headers=headers)
        response = connection.getresponse()
        payload = response.read(65537)
        _require(len(payload) <= 65536)
        if path in ('/api/v1/summary', '/api/v1/audit-status'):
            _require(response.getheader('Cache-Control') == 'no-store')
            _require('Authorization' in response.getheader('Vary', ''))
        _require(response.getheader('Location') is None)
        _require('application/json' in response.getheader('Content-Type', ''))
        return response.status, json.loads(payload)
    finally:
        connection.close()


def run_fixture():
    context = multiprocessing.get_context('spawn')
    with tempfile.TemporaryDirectory(prefix='integration-http-fixture-') as directory:
        state = Path(directory) / 'state.json'
        history = Path(directory) / 'history.jsonl'
        initial = '{"queued":{"private-fixture-title":"2024-01-01"}}'
        state.write_text(initial)
        token = secrets.token_urlsafe(32)
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=_serve_fixture, args=(directory, token, sender), daemon=True)
        started = False
        try:
            process.start()
            started = True
            sender.close()
            _require(receiver.poll(10), 'server_startup_timeout')
            message = receiver.recv()
            _require(message.get('status') == 'ready', 'server_startup_unavailable')
            port = message.get('port')
            _require(type(port) is int and 0 < port < 65536)
            for route in ('/api/v1/summary', '/api/v1/audit-status'):
                _require(_request(port, route)[0] == 401)
                _require(_request(port, route, token='wrong_fixture_token_0123456789012345')[0] == 401)
            code, summary = _request(port, '/api/v1/summary', token=token)
            _require(code == 200 and summary['tracking_counts']['holding'] == 1)
            _require(summary['freshness_verified'] is False and summary['production_authorized'] is False)
            _require('private-fixture-title' not in json.dumps(summary) and token not in json.dumps(summary))
            _require(state.read_text() == initial and not history.exists())
            code, audit = _request(port, '/api/v1/audit-status', token=token)
            _require(code == 200 and audit['running'] is False and audit['last_result'] is None)
            for route in ('/api/run-now', '/api/rescue'):
                _require(_request(port, route, token=token, method='POST')[0] == 401)
            state.write_text('{}')
            code, empty = _request(port, '/api/v1/summary', token=token)
            _require(code == 200 and set(empty['tracking_counts'].values()) == {0})
            for value in (None, '{"queued":[]}'):
                if value is None:
                    state.unlink()
                else:
                    state.write_text(value)
                code, missing = _request(port, '/api/v1/summary', token=token)
                _require(code == 503 and missing['tracking_counts'] is None)
                _require(not state.exists() if value is None else state.read_text() == value)
            history.write_text(json.dumps({'result': 'completed',
                'finished_at': '2024-01-02T00:00:00+00:00', 'error': 'private-error'}) + '\n')
            history_bytes = history.read_bytes()
            code, audit = _request(port, '/api/v1/audit-status', token=token)
            _require(code == 200 and audit['last_result'] == 'completed')
            _require(audit['last_finished'] == '2024-01-02T00:00:00+00:00')
            _require('private-error' not in json.dumps(audit) and history.read_bytes() == history_bytes)
        finally:
            sender.close()
            receiver.close()
            if started:
                if process.is_alive():
                    process.terminate()
                process.join(timeout=3)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=3)
                _require(not process.is_alive())
                process.close()
    return {'status': 'disposable_api_http_smoke_passed', 'fixture_only': True,
            'transport': 'private_loopback_http', 'server_process_stopped': True,
            'production_activation': 'disabled', 'production_authorized': False,
            'external_network_collection_performed': False,
            'widget_rendering_verified': False}


def main():
    if len(sys.argv) != 1:
        print(json.dumps({'status': 'blocked', 'reason': 'fixture_accepts_no_arguments'}))
        return 2
    try:
        report = run_fixture()
    except (Exception, SystemExit) as exc:
        reason = str(exc) if isinstance(exc, FixtureFailure) and str(exc) in (
            'server_startup_timeout', 'server_startup_unavailable',
            'fixture_assertion_failed', 'external_action_forbidden') else 'disposable_http_fixture_failed'
        report = {'status': 'blocked', 'reason': reason,
                  'production_activation': 'disabled', 'production_authorized': False}
    print(json.dumps(report, sort_keys=True))
    return 0 if report['status'] == 'disposable_api_http_smoke_passed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
