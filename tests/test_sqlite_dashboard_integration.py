"""Feature-flag integration against the actual dashboard Flask app."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
SCRIPT = """
import json
from unittest.mock import patch
import web
from flask import g, render_template_string
client = web.app.test_client()
path = '/experimental/sqlite/recovery'
api = '/api/experimental/sqlite/recovery-status'
result = {
    'view_registered': path in [r.rule for r in web.app.url_map.iter_rules()],
    'api_registered': api in [r.rule for r in web.app.url_map.iter_rules()],
    'anonymous_view': client.get(path).status_code,
    'anonymous_api': client.get(api).status_code,
}
with patch.object(web, 'current_user', return_value={'name': 'Viewer', 'admin': False}):
    result['viewer_view'] = client.get(path).status_code
    result['viewer_api'] = client.get(api).status_code
with patch.object(web, 'current_user', return_value={'name': 'Admin', 'admin': True}):
    result['admin_view'] = client.get(path).status_code
    result['admin_api'] = client.get(api).status_code
    result['admin_post'] = client.post(api).status_code
with web.app.test_request_context('/'):
    g.user = {'name': 'Admin', 'admin': True}
    result['admin_nav'] = '/experimental/sqlite/recovery' in render_template_string(
        '{% if viewer.admin and experimental_sqlite_recovery_enabled %}'
        '<a href="/experimental/sqlite/recovery">Recovery</a>{% endif %}'
    )
    g.user = {'name': 'Viewer', 'admin': False}
    result['viewer_nav'] = '/experimental/sqlite/recovery' in render_template_string(
        '{% if viewer.admin and experimental_sqlite_recovery_enabled %}'
        '<a href="/experimental/sqlite/recovery">Recovery</a>{% endif %}'
    )
print('RECOVERY_INTEGRATION=' + json.dumps(result))
"""


def probe(tmp_path, enabled, database=None):
    env = dict(os.environ)
    env["WEB_SESSION_SECRET"] = "test-only-integration-session-secret"
    env["EXPERIMENTAL_SQLITE_RECOVERY_VIEW"] = enabled
    env["EXPERIMENTAL_SQLITE_RECOVERY_DB"] = str(
        database or tmp_path / "missing.db"
    )
    env["PYTHONPATH"] = str(APP) + os.pathsep + str(ROOT)
    result = subprocess.run(
        [sys.executable, "-c", SCRIPT],
        env=env, cwd=ROOT, capture_output=True, text=True, timeout=30,
        check=True,
    )
    return json.loads(result.stdout.split("RECOVERY_INTEGRATION=")[-1].strip())


def test_feature_disabled_by_default(tmp_path):
    result = probe(tmp_path, "false")
    assert result["view_registered"] is False
    assert result["api_registered"] is False
    assert result["admin_view"] == 404
    assert result["admin_api"] == 404


def test_opt_in_uses_real_dashboard_admin_auth(tmp_path):
    result = probe(tmp_path, "true")
    assert result["view_registered"] is True
    assert result["api_registered"] is True
    assert result["anonymous_view"] == 302
    assert result["anonymous_api"] == 401
    assert result["viewer_view"] == 403
    assert result["viewer_api"] == 403
    assert result["admin_view"] == 503
    assert result["admin_api"] == 503
    assert result["admin_post"] == 405


def test_flag_requires_literal_true(tmp_path):
    assert probe(tmp_path, "1")["view_registered"] is False


def test_navigation_is_only_visible_to_admin_when_enabled(tmp_path):
    disabled = probe(tmp_path, "false")
    enabled = probe(tmp_path, "true")
    assert disabled["admin_nav"] is False
    assert enabled["admin_nav"] is True
    assert enabled["viewer_nav"] is False


def test_dashboard_template_has_conditional_recovery_link():
    template = (APP / "templates" / "_sidebar.html").read_text()
    assert "{% if experimental_sqlite_recovery_enabled %}" in template
    assert 'href="/experimental/sqlite/recovery"' in template
