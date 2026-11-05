"""Selected packet integrity is not a current-state backup or restore claim."""
import hashlib
import json
import os
from datetime import datetime,timedelta,timezone
import pytest
from tests.test_integration_api import api,AUTH,TOKEN
from app.json_backup import create_backup
from app.tracking_schema import SECTIONS
import web


@pytest.fixture
def packet_api(api,tmp_path,monkeypatch):
    client,state=api
    root=tmp_path/'backup'
    source=tmp_path/'source.json';source.write_text(json.dumps({key:{} for key in SECTIONS}))
    config=tmp_path/'config.json';config.write_text('{"private":"private-secret"}')
    create_backup(state_file=source,config_file=config,directory=root)
    def select():
        info=root.stat()
        monkeypatch.setenv('INTEGRATION_API_BACKUP_DIRECTORY',str(root))
        monkeypatch.setenv('INTEGRATION_API_BACKUP_IDENTITY',f'{info.st_dev}:{info.st_ino}')
        monkeypatch.setenv('INTEGRATION_API_BACKUP_FINGERPRINT',hashlib.sha256((root/'backup-complete.json').read_bytes()).hexdigest())
    select()
    return client,state,root,select


def test_auth_before_inspection_and_query_cannot_select_packet(packet_api,monkeypatch):
    client,*_=packet_api
    monkeypatch.setattr(web,'selected_backup_status',lambda:pytest.fail('No inspection'))
    assert client.get('/api/v1/backup-status').status_code==401
    assert client.get('/api/v1/backup-status?directory=/private',headers=AUTH).status_code==400


def test_verified_packet_redacted_and_unchanged(packet_api):
    client,state,root,_=packet_api
    before={p.name:p.read_bytes() for p in root.iterdir()};state_before=state.read_bytes()
    response=client.get('/api/v1/backup-status',headers=AUTH)
    assert response.status_code==200
    report=response.json
    assert report['packet_verified'] and report['payload_files_verified']==2
    assert report['capture_time_status']=='recorded' and report['age_seconds']>=0
    assert report['restore_tested'] is False and report['restore_authorized'] is False
    assert report['current_state_comparison']=='not_performed' and report['freshness_verified'] is False
    assert report['backup_scope']=='explicitly_selected_packet'
    assert all(secret not in response.text for secret in (TOKEN,'private-secret',str(root),'sha256','Movies/Fixture','TV/Fixture'))
    assert response.headers['Cache-Control']=='no-store'
    assert before=={p.name:p.read_bytes() for p in root.iterdir()}
    assert state.read_bytes()==state_before


@pytest.mark.parametrize('timestamp',[None,'bad-private-value','2026-01-01T00:00:00','2999-01-01T00:00:00+00:00'])
def test_unknown_and_future_capture_age_never_uses_mtime(packet_api,timestamp):
    client,_,root,select=packet_api
    path=root/'backup-complete.json';receipt=json.loads(path.read_bytes())
    if timestamp is None:receipt.pop('captured_at',None)
    else:receipt['captured_at']=timestamp
    path.write_text(json.dumps(receipt));select()
    response=client.get('/api/v1/backup-status',headers=AUTH)
    assert response.status_code==200
    assert response.json['age_seconds'] is None
    assert response.json['capture_time_status']==('future' if timestamp and timestamp.startswith('2999') else 'unknown')
    assert 'bad-private-value' not in response.text


@pytest.mark.parametrize('failure',['payload','receipt','missing','symlink','hardlink','directory_replaced'])
def test_corrupt_partial_or_replaced_packet_is_not_adopted(packet_api,failure):
    client,_,root,select=packet_api
    if failure=='payload':(root/'saved-config.json').write_text('private changed')
    elif failure=='receipt':(root/'backup-complete.json').write_text('{}')
    elif failure=='missing':(root/'backup-complete.json').unlink()
    elif failure in ('symlink','hardlink'):
        target=root/'saved-config.json';other=root.parent/'elsewhere';target.rename(other)
        if failure=='symlink':target.symlink_to(other)
        else:os.link(other,target)
    else:
        root.rename(root.parent/'retained');root.mkdir(mode=0o700)
    response=client.get('/api/v1/backup-status',headers=AUTH)
    assert response.status_code==503 and response.json['packet_verified'] is False
    assert response.json['verified_at'] is None
    assert 'private changed' not in response.text


def test_unconfigured_and_partial_selection_are_explicit(api,monkeypatch):
    client,_=api
    for key in ('DIRECTORY','IDENTITY','FINGERPRINT'):monkeypatch.delenv('INTEGRATION_API_BACKUP_'+key,raising=False)
    assert client.get('/api/v1/backup-status',headers=AUTH).json['status']=='not_configured'
    monkeypatch.setenv('INTEGRATION_API_BACKUP_DIRECTORY','/private')
    response=client.get('/api/v1/backup-status',headers=AUTH)
    assert response.status_code==503 and response.json['status']=='selection_invalid'
    assert '/private' not in response.text




def test_shared_inspector_budget_refuses_before_returning_verified(packet_api):
    from app.json_backup import inspect_backup as inspect_update_backup
    client,_,root,select=packet_api
    with pytest.raises(RuntimeError):
        inspect_update_backup(directory=root,expected_identity=(root.stat().st_dev,root.stat().st_ino),
            expected_fingerprint=hashlib.sha256((root/'backup-complete.json').read_bytes()).hexdigest(),max_total_bytes=1)
