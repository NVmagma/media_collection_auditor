"""Recovery at rename/checkpoint boundaries never repeats a filesystem move."""
from copy import deepcopy
from datetime import timedelta, timezone
import json
from pathlib import Path

import pytest
from app.json_move_execution import execute_move
from app.json_operation_recovery import (review_pending_move,reconcile_pending_move,
    review_pending_sync,acknowledge_pending_sync,finish_pending_sync)
from app.json_scan_control import KEY,scan_attempt
from test_json_move_execution import move_case,transports,NOW,SIG


def interrupt(case,monkeypatch,phase):
    import app.json_move_execution as module
    store,roots,requests,server=case; request=requests['Movies']
    original=module.rename_directory_noreplace_at
    def stop(*args):
        if phase == 'before_rename': raise RuntimeError('synthetic stop before rename')
        original(*args); raise RuntimeError('synthetic stop after rename')
    with monkeypatch.context() as patch:
        patch.setattr(module,'rename_directory_noreplace_at',stop)
        with pytest.raises(RuntimeError):
            with scan_attempt(store,now=NOW.replace(tzinfo=timezone.utc),trigger='manual') as attempt:
                before,complete=transports(attempt,request,server)
                execute_move(attempt,request=request,now=NOW,fetch_protection=lambda _:dict(SIG),
                    arr_preflight=before,arr_complete=complete)
    return store,request,server


def reader(server): return lambda req:deepcopy(server.records['/api/v3/movie/1'])


def test_source_verified_unperformed_intent_can_be_canceled_without_any_actions(move_case,monkeypatch):
    store,request,server=interrupt(move_case,monkeypatch,'before_rename')
    before=json.loads(store.path.read_bytes()); report=review_pending_move(store,read_record=reader(server))
    assert report['physical_location'] == 'source' and report['required_action'] == 'cancel_unperformed_move'
    assert json.loads(store.path.read_bytes()) == before
    result=reconcile_pending_move(store,read_record=reader(server),expected_fingerprint=report['review_fingerprint'])
    expected=deepcopy(before); expected[KEY]['journal']=None
    assert json.loads(store.path.read_bytes()) == expected
    assert result['status'] == 'unperformed_move_canceled' and not result['arr_sync_pending']
    assert (Path(request.source_root)/request.title/'video.mkv').exists()
    assert not any(method == 'PUT' for method,_ in server.calls)


def test_after_rename_records_original_move_clock_then_requires_explicit_sync(move_case,monkeypatch):
    store,request,server=interrupt(move_case,monkeypatch,'after_rename')
    before=json.loads(store.path.read_bytes()); report=review_pending_move(store,read_record=reader(server))
    assert report['physical_location'] == 'destination' and report['remote_outcome'] == 'source'
    result=reconcile_pending_move(store,read_record=reader(server),expected_fingerprint=report['review_fingerprint'])
    current=json.loads(store.path.read_bytes())
    assert result['arr_sync_pending'] and current[KEY]['journal']['kind'] == 'arr_sync'
    assert current['queued']['Movie'] == NOW.isoformat() and 'Movie' not in current['first_seen']
    assert current[KEY]['last_started_at'] == before[KEY]['last_started_at']
    assert current['unknown'] == before['unknown'] and not any(method == 'PUT' for method,_ in server.calls)
    sync=review_pending_sync(store,read_record=reader(server))
    assert sync['required_action'] == 'finish_arr_sync'
    with pytest.raises(RuntimeError):
        acknowledge_pending_sync(store,read_record=reader(server),expected_fingerprint=sync['review_fingerprint'])
    # The explicit reviewed action sends one update; it never renames the folder again.
    from app.sqlite_arr_title_transport import ArrTitleUpdate
    from time import monotonic
    client=ArrTitleUpdate(service='radarr',base_url='http://127.0.0.1:'+str(server.server_port),
        token='synthetic-token',source_path=request.arr_source_path,title_folder=request.title)
    read=lambda req:client._request('GET',client._url+'/'+str(req.title_id),monotonic()+10)
    def send(req): return client(dict(service=req.service,title_id=req.title_id,root=req.arr_destination_root,monitored=req.monitored))
    result=finish_pending_sync(store,read_record=read,send_update=send,expected_fingerprint=sync['review_fingerprint'])
    assert result['status'] == 'reviewed_arr_sync_completed'
    assert json.loads(store.path.read_bytes())[KEY]['journal'] is None
    assert sum(method == 'PUT' for method,_ in server.calls) == 1
    assert (Path(request.destination_root)/request.title/'video.mkv').exists()


def test_remote_destination_already_verified_records_clock_without_put(move_case,monkeypatch):
    store,request,server=interrupt(move_case,monkeypatch,'after_rename')
    server.records['/api/v3/movie/1'].update(path=request.arr_destination_root+'/'+request.title,monitored=request.monitored)
    report=review_pending_move(store,read_record=reader(server))
    result=reconcile_pending_move(store,read_record=reader(server),expected_fingerprint=report['review_fingerprint'])
    assert not result['arr_sync_pending']
    state=json.loads(store.path.read_bytes())
    assert state['queued']['Movie'] == NOW.isoformat() and state[KEY]['journal'] is None
    assert not any(method == 'PUT' for method,_ in server.calls)


@pytest.mark.parametrize('change',['replacement','both_present','remote_change','stale_review'])
def test_changed_or_ambiguous_move_never_clears_intent(move_case,monkeypatch,change):
    store,request,server=interrupt(move_case,monkeypatch,'after_rename')
    report=review_pending_move(store,read_record=reader(server))
    target=Path(request.destination_root)/request.title
    if change == 'replacement':
        target.rename(target.with_name('retained-original')); target.mkdir(); (target/'video.mkv').write_bytes(b'different')
    elif change == 'both_present': (Path(request.source_root)/request.title).mkdir()
    elif change == 'remote_change': server.records['/api/v3/movie/1']['path']='/changed/Movie'
    else:
        with store.session() as session: session.state['unknown']['changed']=True; session.checkpoint()
    before=store.path.read_bytes()
    with pytest.raises(RuntimeError):
        reconcile_pending_move(store,read_record=reader(server),expected_fingerprint=report['review_fingerprint'])
    assert store.path.read_bytes() == before


def test_failed_explicit_sync_consumes_review_without_automatic_retry(move_case,monkeypatch):
    store,request,server=interrupt(move_case,monkeypatch,'after_rename')
    move=review_pending_move(store,read_record=reader(server))
    reconcile_pending_move(store,read_record=reader(server),expected_fingerprint=move['review_fingerprint'])
    sync=review_pending_sync(store,read_record=reader(server)); calls=[]
    def fail(_): calls.append('PUT attempt'); raise TimeoutError('synthetic lost reply')
    with pytest.raises(TimeoutError): finish_pending_sync(store,read_record=reader(server),send_update=fail,
        expected_fingerprint=sync['review_fingerprint'])
    pending=json.loads(store.path.read_bytes())
    assert pending[KEY]['journal']['details']['dispatch_attempts'] == 1
    with pytest.raises(RuntimeError): finish_pending_sync(store,read_record=reader(server),send_update=fail,
        expected_fingerprint=sync['review_fingerprint'])
    assert calls == ['PUT attempt']
