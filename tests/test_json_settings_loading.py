"""Malformed or missing saved preview settings cannot fall back into live mode."""
import json
from pathlib import Path
import pytest
import config_store
from app.json_worker_service import settings_snapshot,read_saved_settings,JSONWorkerService


@pytest.fixture
def saved(tmp_path,monkeypatch):
    path=tmp_path/'config.json'; monkeypatch.setattr(config_store,'CONFIG_FILE',path)
    monkeypatch.setattr(config_store,'initial_environment',lambda:{'DRY_RUN':'false','MAX_ACTIONS_PER_RUN':'10'})
    return path


def test_saved_preview_stays_preview_and_unknown_fields_remain_inert(saved):
    saved.write_text(json.dumps({'DRY_RUN':'true','unrecognized':{'private':'synthetic'}}))
    values=settings_snapshot()
    assert values['DRY_RUN']=='true' and 'unrecognized' not in values
    assert read_saved_settings()['unrecognized']=={'private':'synthetic'}


@pytest.mark.parametrize('contents',[None,b'{"DRY_RUN":',b'[]',b'{"DRY_RUN":"true","DRY_RUN":"false"}',
    b'{"DRY_RUN":"maybe"}',b'{"MAX_ACTIONS_PER_RUN":"not-a-number"}'])
def test_unavailable_settings_never_select_environment_live_defaults(saved,contents):
    if contents is not None: saved.write_bytes(contents)
    with pytest.raises(ValueError): settings_snapshot()
    worker=JSONWorkerService(load_settings=settings_snapshot)
    assert worker.request()['status']=='review_required'
    assert worker.report()['execution_blocked'] and not worker.report()['queued']
    if contents is None: assert not saved.exists()
    else: assert saved.read_bytes()==contents


def test_symlink_or_hardlinked_configuration_is_not_adopted(saved,tmp_path):
    source=tmp_path/'original.json'; source.write_bytes(b'{"DRY_RUN":"true"}')
    saved.symlink_to(source)
    with pytest.raises(ValueError): settings_snapshot()
    saved.unlink()
    import os
    os.link(source,saved)
    with pytest.raises(ValueError): settings_snapshot()
    assert source.read_bytes()==b'{"DRY_RUN":"true"}'


def test_missing_tracking_is_not_rendered_as_a_fresh_empty_json_install(tmp_path,monkeypatch):
    from app.integration_status import read_selected_dashboard_state
    monkeypatch.setenv('AUDITOR_WORKER_MODE','json_serialized')
    monkeypatch.setenv('AUDITOR_STATE_BACKEND','json')
    source=tmp_path/'missing-state.json'
    with pytest.raises(RuntimeError): read_selected_dashboard_state(source)
    assert not source.exists()
