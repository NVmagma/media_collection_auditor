"""Authenticated live form applies ordinary changes without a legacy config save."""
from unittest.mock import Mock,patch
import os
import pytest
import config_store,web
from test_sqlite_live_binding import prepared
from app import sqlite_live_binding as live
from app.state_store import GuardedSQLiteStateStore

@pytest.fixture
def page(prepared,monkeypatch):
    _,_,_,config,values=prepared;live.create_live_binding(settings=values)
    monkeypatch.setattr(config_store,'CONFIG_FILE',config)
    monkeypatch.setattr(config_store,'initial_environment',lambda:dict(values))
    monkeypatch.setattr(web,'current_user',lambda:{'name':'Fixture admin','admin':True})
    monkeypatch.setattr(web,'save_config',Mock(side_effect=AssertionError('No legacy write')))
    with patch.dict(os.environ,values):
        yield web.app.test_client(),prepared


def test_live_form_applies_at_advanced_revision_and_masks_secrets(page):
    client,prepared=page;_,_,control,config,values=prepared
    store=GuardedSQLiteStateStore(control/'state.db');state,revision=store.load_with_revision()
    state['unknown-latest']=True;store.save_if_revision(state,revision);before=store.load_with_revision()
    form={key:values.get(key,config_store.DEFAULTS.get(key,'')) for key in config_store.KEYS}
    form.update(HOLDING_DAYS='14',settings_action='apply')
    response=client.post('/settings',data=form,headers={'Origin':'http://localhost'})
    assert response.status_code==302 and 'applied=1' in response.location
    assert live.validate_live_binding(settings=values,for_execution=True)['HOLDING_DAYS']=='14'
    assert store.load_with_revision()==before
    html=client.get('/settings').text
    assert 'Apply Requested Settings' in html and 'Fixed for this canary' in html
    assert 'Type I UNDERSTAND' not in html and 'Save Changes' not in html
    assert 'synthetic-token' not in html
    web.save_config.assert_not_called()


def test_cross_origin_or_readonly_cannot_apply_live_settings(page,monkeypatch):
    client,_=page
    assert client.post('/settings/apply',headers={'Origin':'http://different.invalid'}).status_code==403
    monkeypatch.setattr(web,'current_user',lambda:{'name':'Viewer','admin':False})
    assert client.post('/settings/apply',headers={'Origin':'http://localhost'}).status_code==403
