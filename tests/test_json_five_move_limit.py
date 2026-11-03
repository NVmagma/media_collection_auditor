"""Five independent slots per library; a sixth move cannot reach the filesystem."""
from dataclasses import replace
from datetime import timezone
import json
from pathlib import Path

import pytest
from app.json_move_execution import execute_move
from app.json_scan_control import scan_attempt
from app.json_lifecycle_plan import plan_scan,LibraryObservation,TitleObservation
from test_json_move_execution import move_case,transports,NOW,SIG
from test_json_tracking_store import state


def test_planner_selects_five_movies_and_five_shows_and_keeps_all_decisions():
    snapshot=state(); snapshot['first_seen']={}
    libraries=[]
    for library in ('Movies','TV'):
        rows=[]
        for index in range(7):
            key=('TV/' if library=='TV' else '')+f'Title {index}'
            snapshot['first_seen'][key]='2026-01-01T01:02:03'
            rows.append(TitleObservation(key,'Waiting',30,dict(SIG),'exact_source_match'))
        libraries.append(LibraryObservation(library,True,True,tuple(rows)))
    result=plan_scan(snapshot=snapshot,libraries=libraries,now=NOW,per_library_action_limit=5)
    assert len(result['decisions']) == 14 and len(result['moves']) == 10
    assert [row.library for row in result['moves']].count('TV') == 5
    assert sum(row.outcome=='capped' for row in result['decisions']) == 4


def test_executor_performs_five_but_refuses_sixth_before_any_request(move_case):
    store,roots,requests,server=move_case; template=requests['Movies']; moves=[template]
    with store.session() as session:
        for index in range(1,6):
            title='Movie '+str(index); path=Path(template.source_root)/title
            path.mkdir(); (path/'video.mkv').write_bytes(b'disposable-media')
            request=replace(template,title=title,title_id=index+10,arr_source_path=str(path))
            moves.append(request); session.state['first_seen'][title]=template.source_since
            server.records['/api/v3/movie/'+str(request.title_id)]={
                'id':request.title_id,'path':request.arr_source_path,'monitored':True}
        session.checkpoint()
    with scan_attempt(store,now=NOW.replace(tzinfo=timezone.utc),trigger='manual') as attempt:
        for request in moves[:5]:
            before,complete=transports(attempt,request,server)
            execute_move(attempt,request=request,now=NOW,fetch_protection=lambda _:dict(SIG),
                arr_preflight=before,arr_complete=complete,per_library_limit=5)
        calls=list(server.calls); last=moves[5]
        with pytest.raises(RuntimeError):
            execute_move(attempt,request=last,now=NOW,fetch_protection=lambda _:pytest.fail('Limit first'),
                arr_preflight=lambda _:pytest.fail('No request'),arr_complete=lambda _:pytest.fail('No update'),
                per_library_limit=5)
        assert server.calls == calls
        attempt.finish(result='completed')
    current=json.loads(store.path.read_bytes())
    assert len(current['queued']) == 5 and last.title in current['first_seen']
    assert (Path(last.source_root)/last.title/'video.mkv').exists()
    assert sum(method=='PUT' for method,_ in server.calls) == 5
