"""Status presentation preserves explicit apply/restore controls and hidden secrets."""
from html.parser import HTMLParser
import pytest
from settings_workspace_case import render_settings_workspace


class Elements(HTMLParser):
    def __init__(self):
        super().__init__(); self.elements=[]
    def handle_starttag(self, tag, attrs):
        self.elements.append((tag,dict(attrs)))


def test_pending_fields_are_names_only_and_active_values_are_not_replaced():
    page=render_settings_workspace(); parsed=Elements(); parsed.feed(page)
    assert 'Settings request pending' in page and 'Requested field names (3)' in page
    assert 'Manage TV Shows' in page and 'Apply Requested Settings' in page
    assert 'Save Requested Changes' not in page and 'I UNDERSTAND' not in page
    inputs={attrs.get('name'):attrs for tag,attrs in parsed.elements if tag=='input'}
    assert inputs['JELLYFIN_API_TOKEN']['value']==''
    assert inputs['HOLDING_DAYS']['value']=='7'
    forms={attrs['action'] for tag,attrs in parsed.elements if tag=='form'}
    assert '/settings/apply' not in forms and '/settings/restore' not in forms
    assert inputs['settings_action']['value']=='apply'
    assert inputs['request_sha256']['value']=='a'*64
    assert 'settings.js' in page


@pytest.mark.parametrize('scenario', ['stale','clean','review','resubmit'])
def test_nonready_states_cannot_select_an_existing_request_without_new_edits(scenario):
    page=render_settings_workspace(scenario)
    assert 'action="/settings/apply"' not in page
    assert 'action="/settings/restore"' not in page
    assert 'id="settings-form"' in page
    assert 'id="apply-settings-button"' in page
    assert 'name="request_sha256"' not in page


def test_interrupted_state_locks_editor_but_keeps_explicit_restore_outside_it():
    page=render_settings_workspace('recovery'); parsed=Elements(); parsed.feed(page)
    assert 'before editing again' in page and 'Restore Previous Settings' in page
    assert any(tag=='fieldset' and 'disabled' in attrs for tag,attrs in parsed.elements)
    assert page.index('action="/settings/restore"')<page.index('id="settings-form"')
    assert 'action="/settings/apply"' not in page
