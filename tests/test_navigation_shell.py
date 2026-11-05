"""All authenticated pages share destinations, role boundaries and a left sidebar."""
from html.parser import HTMLParser
from flask import g,render_template
import web
from dashboard_workspace_case import render_workspace
from settings_workspace_case import render_settings_workspace,render_integration_workspace

class Navigation(HTMLParser):
    def __init__(self,page):
        super().__init__();self.sidebar=False;self.links=[];self.feed(page)
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='aside':self.sidebar=True
        if self.sidebar and tag=='a':self.links.append(attrs.get('href'))
    def handle_endtag(self,tag):
        if tag=='aside':self.sidebar=False

def render_page(name,admin=True):
    with web.app.test_request_context('/'):
        g.user={'name':'Synthetic reviewer','admin':admin}
        return render_template(name,actions=[],live_mode=True)

def test_all_administrator_screens_have_same_navigation_and_signout():
    pages=[render_workspace(admin=True).text,render_workspace(admin=True,workspace='Review').text,
        render_settings_workspace(),render_integration_workspace(),render_page('logs.html'),
        render_page('preview-paused.html')]
    expected=Navigation(pages[0]).links
    for page in pages:
        assert Navigation(page).links==expected
        assert 'id="main-content"' in page
        assert 'href="#main-content"' in page
        assert 'aria-label="Sign out"' in page
        assert 'class="topbar"' not in page
    assert '/settings' in expected and '/integrations' in expected and '/review' in expected
