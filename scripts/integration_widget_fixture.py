#!/usr/bin/env python3
"""Container-only, expiring, synthetic dashboard API; no auditor worker."""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import stat
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from flask import Flask, request
from app.integration_api import authorize_summary
from app.integration_status import audit_status_report, read_tracking_status, read_tracking_titles


def read_fixture_token(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError('Invalid fixture credential')
        raw = os.read(descriptor, 258)
    finally:
        os.close(descriptor)
    if raw.endswith(b'\n'):
        raw = raw[:-1]
    if not re.fullmatch(rb'[A-Za-z0-9_-]{32,256}', raw):
        raise ValueError('Invalid fixture credential')
    return raw.decode('ascii')


def create_fixture_app(directory, scenario):
    if scenario not in ('sample', 'titles', 'empty', 'unavailable'):
        raise ValueError('Unsupported fixture scenario')
    state = Path(directory) / 'state.json'
    if state.exists() or state.is_symlink():
        raise ValueError('Fixture slot must be new')
    sample = {'first_seen': {'Fixture A': '2024-01-01', 'Fixture B': '2024-01-01'},
              'queued': {'Fixture C': '2024-01-01'},
              'keep_seen': {'Fixture D': '2024-01-01'},
              'in_removal': {'Fixture E': '2024-01-01'},
              'arr_sync_pending': {'Fixture C': {'stage': 'holding', 'root': '/fixture/holding'}}}
    if scenario == 'titles':
        sample = {
            'first_seen': {f'Fixture Movie {n:02}': f'2024-01-{n:02}' for n in range(1, 13)},
            'queued': {f'TV/Fixture Series {n:02}': f'2024-02-{n:02}' for n in range(1, 13)},
        }
    if scenario != 'unavailable':
        with state.open('x') as handle:
            json.dump(sample if scenario in ('sample', 'titles') else {}, handle)
    app = Flask('auditor_widget_fixture')
    app.config.update(DEBUG=False, TESTING=False)

    @app.before_request
    def authorize():
        if request.path not in ('/api/v1/summary', '/api/v1/audit-status',
                                '/api/v1/titles/oldest-waiting', '/api/v1/titles/leaving-soon'):
            return {'status': 'fixture_route_unavailable'}, 404
        error = authorize_summary(request.headers.get('Authorization'))
        if error is not None:
            return error
        if request.method not in ('GET', 'HEAD'):
            return {'status': 'fixture_method_unavailable'}, 405

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Vary'] = 'Authorization'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.get('/api/v1/summary')
    def summary():
        report = read_tracking_status(state)
        report['fixture_only'] = True
        return report, 503 if report['status'] == 'unavailable' else 200

    @app.get('/api/v1/titles/oldest-waiting', defaults={'view': 'oldest-waiting'})
    @app.get('/api/v1/titles/leaving-soon', defaults={'view': 'leaving-soon'})
    def titles(view):
        report = read_tracking_titles(state, view)
        report['fixture_only'] = True
        return report, 503 if report['status'] == 'unavailable' else 200

    @app.get('/api/v1/audit-status')
    def audit():
        current = None if scenario == 'unavailable' else {
            'running': False, 'queued': False, 'rescuing': False,
            'last_result': 'completed' if scenario == 'sample' else None,
            'last_finished': '2024-01-01T01:00:00+00:00' if scenario == 'sample' else None}
        report = audit_status_report(current)
        report['fixture_only'] = True
        return report, 503 if report['status'] == 'unavailable' else 200

    @app.errorhandler(Exception)
    def unavailable(error):
        return {'status': 'fixture_unavailable', 'fixture_only': True}, 503

    return app


def serve_fixture(app, seconds):
    from socketserver import TCPServer
    from wsgiref.simple_server import WSGIServer, WSGIRequestHandler

    class Handler(WSGIRequestHandler):
        def log_message(self, *args, **kwargs):
            pass

    class Server(WSGIServer):
        def server_bind(self):
            TCPServer.server_bind(self)
            self.server_name = 'widget-fixture'
            self.server_port = self.server_address[1]
            self.setup_environ()
        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(5)
            return connection, address

    with Server(('0.0.0.0', 8080), Handler) as server:
        server.set_app(app)
        server.timeout = 1
        deadline = time.monotonic() + seconds
        print(json.dumps({'status': 'widget_fixture_ready', 'fixture_only': True,
                          'lifetime_seconds': seconds, 'scenario_source': 'synthetic',
                          'production_authorized': False}), flush=True)
        while time.monotonic() < deadline:
            server.handle_request()
    print(json.dumps({'status': 'widget_fixture_expired', 'fixture_only': True}), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--token-file', required=True)
    parser.add_argument('--scenario', choices=('sample', 'titles', 'empty', 'unavailable'), default='sample')
    parser.add_argument('--lifetime-seconds', type=int, default=900)
    args = parser.parse_args(argv)
    if not Path('/.dockerenv').is_file() or not 30 <= args.lifetime_seconds <= 3600:
        print(json.dumps({'status': 'blocked', 'reason': 'container_and_bounded_lifetime_required'}))
        return 2
    try:
        os.environ['INTEGRATION_API_TOKEN'] = read_fixture_token(args.token_file)
        # A hard process deadline also bounds a stalled/slow HTTP client. The
        # container owns all synthetic files; --rm discards its tmpfs on exit.
        signal.signal(signal.SIGALRM, lambda *unused: os._exit(0))
        signal.alarm(args.lifetime_seconds)
        with tempfile.TemporaryDirectory(prefix='widget-api-synthetic-') as directory:
            app = create_fixture_app(directory, args.scenario)
            serve_fixture(app, args.lifetime_seconds)
    except (OSError, ValueError, RuntimeError):
        print(json.dumps({'status': 'blocked', 'reason': 'widget_fixture_unavailable'}))
        return 2
    finally:
        signal.alarm(0)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
