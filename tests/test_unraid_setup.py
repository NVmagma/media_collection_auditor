"""Template-only onboarding and saved settings must preserve old state and deny takeover."""
import json
import xml.etree.ElementTree as ET
from pathlib import Path
import pytest
import config_store
import web
from app import unraid_setup as setup


@pytest.fixture
def installation(tmp_path, monkeypatch):
    root = tmp_path / 'logs'; root.mkdir()
    monkeypatch.setattr(config_store, 'CONFIG_FILE', root / 'auditor_config.json')
    monkeypatch.setattr(setup, 'CONFIG_FILE', config_store.CONFIG_FILE)
    monkeypatch.delenv('WEB_ADMIN_PASSWORD', raising=False)
    return root


def test_empty_appdata_setup_is_one_time_hashed_and_safe(installation, capsys):
    setup.prepare_installation()
    token = (installation/'setup-token').read_text().strip()
    assert token in capsys.readouterr().out
    original = (installation/'auditor_state.json').read_bytes()
    with pytest.raises(ValueError): setup.complete_setup('wrong', 'admin', 'a-long-test-password')
    with pytest.raises(ValueError): setup.complete_setup('☃', 'admin', 'a-long-test-password')
    with pytest.raises(ValueError): setup.complete_setup(token, 'admin', 'short')
    setup.complete_setup(token, 'admin', 'a-long-test-password')
    assert setup.authenticate('admin','a-long-test-password')
    assert not setup.authenticate('admin','wrong')
    assert not setup.setup_pending()
    assert not (installation/'setup-token').exists()
    saved = json.loads(config_store.CONFIG_FILE.read_text())
    assert 'a-long-test-password' not in config_store.CONFIG_FILE.read_text()
    assert saved['DRY_RUN']=='true' and saved['ALLOW_TV_SEASON_DELETE']=='false'
    assert (installation/'auditor_state.json').read_bytes()==original
    setup.prepare_installation()
    assert (installation/'auditor_state.json').read_bytes()==original


def test_nonempty_partial_appdata_is_never_reinitialized(installation):
    (installation/'auditor_state.json').write_text('damaged state')
    setup.prepare_installation()
    assert not (installation/'setup-token').exists()
    assert not config_store.CONFIG_FILE.exists()
    assert (installation/'auditor_state.json').read_text()=='damaged state'


def test_setup_origin_account_change_and_session_revocation(installation, monkeypatch):
    setup.prepare_installation();token=(installation/'setup-token').read_text().strip()
    client=web.app.test_client()
    fields={'code':token,'username':'admin','password':'a-long-test-password'}
    assert client.post('/setup',data=fields).status_code==403
    assert client.post('/setup',data=fields,headers={'Origin':'http://localhost'}).status_code==302
    monkeypatch.setattr(web,'jellyfin_login',lambda *args:(None,None))
    assert client.post('/login',data={'username':'admin','password':'a-long-test-password'},headers={'Origin':'http://localhost'}).status_code==302
    with client.session_transaction() as session: previous=dict(session)
    assert client.post('/account',data={'username':'new','password':'another-long-password'},headers={'Origin':'http://localhost'}).status_code==403
    assert client.post('/account',data={'current_username':'admin','current_password':'a-long-test-password','username':'new','password':'another-long-password'},headers={'Origin':'http://localhost'}).status_code==302
    assert not setup.authenticate('admin','a-long-test-password')
    assert setup.authenticate('new','another-long-password')
    with client.session_transaction() as session: session.update(previous)
    assert client.get('/settings').status_code==302


def test_saved_api_token_rotation_and_revocation_without_restart(installation, monkeypatch):
    from integration_api import authorize_summary
    config_store.save_config({'INTEGRATION_API_TOKEN':'A'*40})
    monkeypatch.setenv('INTEGRATION_API_TOKEN','legacy-token-'+'X'*32)
    assert authorize_summary('Bearer '+'A'*40) is None
    config_store.save_config({'INTEGRATION_API_TOKEN':'B'*40})
    assert authorize_summary('Bearer '+'A'*40)[1]==401
    assert authorize_summary('Bearer '+'B'*40) is None
    config_store.save_config({'INTEGRATION_API_TOKEN':''})
    assert authorize_summary('Bearer '+'B'*40)[1]==404
    assert authorize_summary('Bearer legacy-token-'+'X'*32)[1]==404


def test_account_and_unknown_fields_survive_settings_apply(installation, monkeypatch):
    setup.prepare_installation(); setup.complete_setup((installation/'setup-token').read_text().strip(),'admin','a-long-test-password')
    saved=json.loads(config_store.CONFIG_FILE.read_text());saved['extension']={'keep':True};config_store.save_config(saved)
    monkeypatch.setattr(web,'current_user',lambda:{'name':'Tester','admin':True})
    client=web.app.test_client()
    response=client.post('/settings',data={'settings_action':'apply','INTEGRATION_API_TOKEN':'C'*40,'INTEGRATION_API_TITLE_DETAILS':'true','TV_SEASON_HOLDING_PATH':'/media/TV_seasons_leaving_soon'},headers={'Origin':'http://localhost'})
    assert response.status_code==302, response.text
    updated=json.loads(config_store.CONFIG_FILE.read_text())
    assert updated[setup.ACCOUNT]==saved[setup.ACCOUNT] and updated['extension']=={'keep':True}
    assert updated['INTEGRATION_API_TOKEN']=='C'*40
    response=client.get('/settings')
    assert 'C'*40 not in response.text and saved[setup.ACCOUNT]['password_hash'] not in response.text
    assert 'data-panel="Account"' in response.text


def test_unraid_template_has_only_deployment_controls():
    root=ET.parse(Path(__file__).resolve().parents[1]/'unraid/template/media_archiver.xml').getroot()
    fields=root.findall('Config')
    assert {f.get('Type') for f in fields}=={'Path','Port'}
    assert {f.get('Target') for f in fields}=={'/app/logs','/media','8080'}
    assert '--read-only' in root.findtext('ExtraParams')
    assert '--cap-drop=ALL' in root.findtext('ExtraParams')


def test_applying_settings_migrates_inherited_secrets_without_rendering_them(installation, monkeypatch):
    setup.prepare_installation()
    monkeypatch.setattr(config_store, '_INITIAL_ENVIRONMENT', {'JELLYFIN_API_TOKEN':'private-legacy-key', 'INTEGRATION_API_TOKEN':'L'*40})
    monkeypatch.setattr(web, 'current_user', lambda:{'name':'Tester','admin':True})
    client=web.app.test_client()
    before=(installation/'auditor_state.json').read_bytes()
    response=client.post('/settings',data={'settings_action':'apply','JELLYFIN_API_TOKEN':'','INTEGRATION_API_TOKEN':''},headers={'Origin':'http://localhost'})
    assert response.status_code==302
    saved=json.loads(config_store.CONFIG_FILE.read_text())
    assert saved['JELLYFIN_API_TOKEN']=='private-legacy-key' and saved['INTEGRATION_API_TOKEN']=='L'*40
    page=client.get('/settings').text
    assert 'private-legacy-key' not in page and 'L'*40 not in page
    assert (installation/'auditor_state.json').read_bytes()==before
