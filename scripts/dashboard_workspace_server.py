"""Expiring synthetic dashboard preview; no auditor worker or production configuration."""
import argparse
from pathlib import Path
import threading
from flask import Flask, Response, request, send_file
from werkzeug.serving import make_server
from dashboard_workspace_case import render_workspace


def create_preview_app():
    root = Path(__file__).resolve().parents[1]
    app = Flask('dashboard_workspace_fixture', static_folder=str(root / 'app/static'))

    @app.get('/')
    def dashboard():
        page = render_workspace().get_data(as_text=True)
        page = page.replace('<main>', '<main><p class="notice" role="status">Disposable design preview · synthetic titles only · no production services connected.</p>', 1)
        return Response(page, mimetype='text/html')

    @app.get('/static/auditor-badge.png')
    def badge():
        return send_file(root / 'unraid/assets/Media_Collection_Auditor_Badge.png', mimetype='image/png')

    @app.before_request
    def read_only():
        if request.method not in ('GET', 'HEAD'):
            return {'status': 'fixture_read_only', 'production_authorized': False}, 405

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lifetime-seconds', type=int, default=900)
    args = parser.parse_args()
    if not 30 <= args.lifetime_seconds <= 900:
        parser.error('Lifetime must be between 30 and 900 seconds')
    server = make_server('0.0.0.0', 8080, create_preview_app(), threaded=True)
    timer = threading.Timer(args.lifetime_seconds, server.shutdown)
    timer.daemon = True
    timer.start()
    try:
        server.serve_forever()
    finally:
        timer.cancel()
        server.server_close()


if __name__ == '__main__':
    main()
