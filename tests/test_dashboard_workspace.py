"""Workspace structure preserves authority, escaping and administrator boundaries."""
from html.parser import HTMLParser
from dashboard_workspace_case import render_workspace


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


def test_readonly_workspace_keeps_all_existing_sections_without_action_controls():
    response = render_workspace()
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    parser = Elements(); parser.feed(page)
    assert [attrs['data-workspace'] for _, attrs in parser.elements if 'data-workspace' in attrs] == [
        'Overview', 'Library', 'Audit Preview', 'Activity', 'History']
    assert {attrs['data-panel'] for _, attrs in parser.elements if 'data-panel' in attrs} == {
        'Overview', 'Movies', 'TV Shows', 'Audit Preview', 'Activity', 'History'}
    assert 'id="run-now"' not in page and 'rescue-choice' not in page
    assert 'Saved tracking records' in page and 'these totals can differ' in page
    assert 'The Quiet Orbit (2026)' in page and 'Lantern House (2026)' in page
    assert 'src="/static/dashboard.js" defer' in page
    assert '/static/auditor-badge.png' in page


def test_admin_keeps_manual_preview_and_tracking_errors_do_not_show_zero_totals():
    page = render_workspace(admin=True, tracking_available=False).get_data(as_text=True)
    assert 'id="run-now"' in page and 'data-preview="true"' in page
    assert 'Tracking state unavailable' in page
    counters = page.split('<div class="cards tracking-cards">', 1)[1].split('</div>', 1)[0]
    assert counters.count('<small>Tracking unavailable</small>') == 4
    assert '<strong>—</strong>' in page


def test_disposable_server_has_synthetic_banner_and_refuses_actions():
    from scripts.dashboard_workspace_server import create_preview_app
    client = create_preview_app().test_client()
    assert 'Disposable design preview' in client.get('/').get_data(as_text=True)
    assert client.get('/static/dashboard.js').status_code == 200
    assert client.get('/static/auditor-badge.png').mimetype == 'image/png'
    for endpoint in ('/api/run-now', '/api/rescue', '/settings'):
        assert client.post(endpoint, json={}).status_code == 405
    assert client.get('/api/v1/summary').status_code == 404
