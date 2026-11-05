from copy import deepcopy
from pathlib import Path
import json,os
from concurrent.futures import ThreadPoolExecutor
import pytest
from app import backup_workspace as backups
from app.json_initialize import initialize
from app.json_tracking_store import JsonTrackingStore
from app.state_lock import StateLockBusy
from test_integration_api import api
import config_store,web


@pytest.fixture
def files(tmp_path):
    logs=tmp_path/'logs';logs.mkdir();initialize(logs)
    state=logs/'auditor_state.json';config=logs/'auditor_config.json'
    saved=json.loads(state.read_bytes());saved['first_seen']['Movie']='2020-01-01T01:02:03'
    saved['extension']={'retain':'PRIVATE-TRACKING'}
    saved['json_worker_control']['journal']={'kind':'arr_sync','phase':'intent_recorded','private':'SECRET'}
    state.write_text(json.dumps(saved));config.write_text('{"DRY_RUN":"false","token":"PRIVATE-TOKEN","unknown":{"keep":true}}')
    return state,config


def create(files):
    return backups.create(state_file=files[0],config_file=files[1])


def test_create_verify_and_inert_restore_preserve_all_bytes_and_unknowns(files):
    state,config=files;before=state.read_bytes(),config.read_bytes()
    result=create(files);identifier=result['id']
    listing=backups.inventory(config_file=config)
    assert listing['total']==1 and listing['items'][0]['status']=='verified'
    assert listing['items'][0]['counts']['first_seen']==1 and listing['items'][0]['pending'] is True
    assert 'PRIVATE' not in str(listing) and 'SECRET' not in str(listing)
    assert backups.verify_backup(config_file=config,identifier=identifier)['status']=='backup_verified'
    tested=backups.test_restore(config_file=config,identifier=identifier)
    destination=config.parent/backups.LEAF/'.restore-tests'/tested['test_id']
    assert (destination/'auditor_state.json').read_bytes()==before[0]
    assert (destination/'saved-config.json').read_bytes()==before[1]
    receipt=json.loads((destination/'restore-test-complete.json').read_bytes())
    assert receipt['worker_started'] is False and receipt['active_restore_performed'] is False
    assert (state.read_bytes(),config.read_bytes())==before
    assert config.parent.joinpath(backups.LEAF).stat().st_mode & 0o077==0
    assert all(path.stat().st_mode & 0o077==0 for path in destination.iterdir())


def test_empty_inventory_does_not_initialize_or_adopt_existing_host_packets(files):
    state,config=files;before=list(config.parent.iterdir())
    assert backups.inventory(config_file=config)['total']==0
    assert list(config.parent.iterdir())==before
    root=config.parent/backups.LEAF;root.mkdir(mode=0o700)
    with pytest.raises(FileNotFoundError):backups.inventory(config_file=config)
    assert not (root/'.version').exists()


def test_payload_changes_partial_packets_and_invalid_ids_never_restore(files):
    _,config=files;result=create(files);packet=config.parent/backups.LEAF/result['id']
    (packet/'auditor_state.json').write_text('{}')
    assert backups.inventory(config_file=config)['items'][0]['status']=='unavailable'
    with pytest.raises(RuntimeError):backups.test_restore(config_file=config,identifier=result['id'])
    assert not (packet.parent/'.restore-tests').exists()
    with pytest.raises(ValueError):backups.verify_backup(config_file=config,identifier='../outside')
    partial=packet.parent/('c'*32);partial.mkdir(mode=0o700)
    assert any(row['id']=='c'*32 and row['status']=='unavailable' for row in backups.inventory(config_file=config)['items'])


def test_symlink_or_permissive_root_is_not_written(files,tmp_path):
    _,config=files;outside=tmp_path/'outside';outside.mkdir()
    root=config.parent/backups.LEAF;root.symlink_to(outside,target_is_directory=True)
    with pytest.raises(OSError):create(files)
    assert list(outside.iterdir())==[]
    root.unlink();root.mkdir(mode=0o755);os.chmod(root,0o755)
    with pytest.raises(RuntimeError):create(files)
    assert list(root.iterdir())==[]


def test_collision_and_interrupted_test_copy_are_retained_without_replay(files,monkeypatch):
    _,config=files;result=create(files)
    real=backups._write
    def fail(fd,name,raw):
        if name=='saved-config.json':raise RuntimeError('synthetic interruption')
        real(fd,name,raw)
    monkeypatch.setattr(backups,'_write',fail)
    with pytest.raises(RuntimeError):backups.test_restore(config_file=config,identifier=result['id'])
    tests=config.parent/backups.LEAF/'.restore-tests'
    retained=list(tests.iterdir());assert len(retained)==1
    assert (retained[0]/'auditor_state.json').exists() and not (retained[0]/'restore-test-complete.json').exists()
    monkeypatch.setattr(backups,'_write',real)
    monkeypatch.setattr(backups.secrets,'token_hex',lambda count:retained[0].name)
    with pytest.raises(FileExistsError):backups.test_restore(config_file=config,identifier=result['id'])
    assert not (retained[0]/'restore-test-complete.json').exists()


def test_active_writer_blocks_capture_without_mutating_source(files):
    state,_=files;before=state.read_bytes()
    with JsonTrackingStore(state).session():
        with ThreadPoolExecutor(max_workers=1) as pool:
            with pytest.raises(StateLockBusy):pool.submit(create,files).result()
    assert state.read_bytes()==before


def test_web_requires_admin_origin_csrf_and_keeps_private_content_off_page(api,files,monkeypatch):
    client=api[0];state,config=files
    monkeypatch.setattr(web,'STATE_FILE',str(state));monkeypatch.setattr(config_store,'CONFIG_FILE',config)
    assert client.get('/backups').status_code==302
    monkeypatch.setattr(web,'current_user',lambda:{'name':'Viewer','admin':False})
    assert client.get('/backups').status_code==403
    monkeypatch.setattr(web,'current_user',lambda:{'name':'Admin','admin':True})
    assert client.get('/backups').status_code==200
    with client.session_transaction() as session:csrf=session['backup_csrf']
    data={'action':'create','csrf':csrf}
    assert client.post('/backups',data=data).status_code==403
    assert client.post('/backups',data=data,headers={'Origin':'http://outside.invalid'}).status_code==403
    assert client.post('/backups',data={'action':'create'},headers={'Origin':'http://localhost'}).status_code==403
    response=client.post('/backups',data=data,headers={'Origin':'http://localhost'},follow_redirects=True)
    assert response.status_code==200 and 'backup created and verified' in response.text
    assert response.headers['Cache-Control']=='no-store'
    assert 'PRIVATE-TOKEN' not in response.text and 'PRIVATE-TRACKING' not in response.text and 'SECRET' not in response.text
    identifier=backups.inventory(config_file=config)['items'][0]['id']
    response=client.post('/backups',data={'action':'test_restore','csrf':csrf,'identifier':identifier},headers={'Origin':'http://localhost'},follow_redirects=True)
    assert response.status_code==200 and 'No worker was started' in response.text
    assert client.get('/backups?page=999').status_code==400
    assert client.get('/backups?directory=/private').status_code==400


def test_source_packet_change_during_restore_prevents_completion(files,monkeypatch):
    _,config=files;created=create(files);packet=config.parent/backups.LEAF/created['id']
    real=backups._write
    def change(fd,name,raw):
        real(fd,name,raw)
        if name=='saved-config.json':(packet/'saved-config.json').write_text('{"changed":true}')
    monkeypatch.setattr(backups,'_write',change)
    with pytest.raises(RuntimeError):backups.test_restore(config_file=config,identifier=created['id'])
    tests=config.parent/backups.LEAF/'.restore-tests'
    assert all(not path.joinpath('restore-test-complete.json').exists() for path in tests.iterdir())


def test_retention_bound_refuses_without_deleting_existing_backups(files,monkeypatch):
    _,config=files;created=create(files)
    packet=config.parent/backups.LEAF/created['id'];before={p.name:p.read_bytes() for p in packet.iterdir()}
    monkeypatch.setattr(backups,'LIMIT',1)
    with pytest.raises(RuntimeError):create(files)
    assert {p.name:p.read_bytes() for p in packet.iterdir()}==before
