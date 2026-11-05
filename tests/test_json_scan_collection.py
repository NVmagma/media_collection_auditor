"""Actual loopback GET collection into the JSON plan; no media/Arr mutations."""
from copy import deepcopy
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from urllib.parse import urlsplit, parse_qs

import pytest
from app.json_scan_collection import InventoryTitle, LibraryInventory, collect_readonly_plan

NOW = datetime(2026,1,20,12)


@pytest.fixture
def services():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*a): pass
        def respond(self,value,code=200):
            self.send_response(code); self.end_headers(); self.wfile.write(json.dumps(value).encode())
        def do_POST(self):
            self.server.calls.append(('POST',self.path)); self.respond({},500)
        def do_GET(self):
            self.server.calls.append(('GET',self.path))
            url = urlsplit(self.path); params = parse_qs(url.query)
            if url.path == '/Users':
                assert self.headers['Authorization'] == 'MediaBrowser Token="synthetic-jellyfin-token"'
                return self.respond([{'Id':'user1'},{'Id':'user2'}])
            if url.path.endswith('/Items'):
                kind = params['IncludeItemTypes'][0]
                if (self.server.mode == 'tv_jf_failure' and kind == 'Series'
                        or self.server.mode == 'second_user_failure' and kind == 'Movie' and '/user2/' in url.path):
                    return self.respond({'private':'synthetic-private-response'},401)
                rows = deepcopy(self.server.items[kind])
                if '/user2/' in url.path: rows[0]['UserData']['IsFavorite'] = self.server.favorite
                start, limit = int(params['StartIndex'][0]), int(params['Limit'][0])
                total = len(rows)
                if self.server.mode == 'bad_pagination' and start > 0: total += 1
                return self.respond({'Items':rows[start:start+limit],'TotalRecordCount':total,'StartIndex':start})
            if url.path in ('/api/v3/movie','/api/v3/series'):
                assert self.headers['X-Api-Key'] == 'synthetic-arr-token'
                if self.server.mode == 'sonarr_failure' and url.path.endswith('series'):
                    return self.respond({'private':'synthetic-private-response'},503)
                return self.respond(self.server.catalogs[url.path.rsplit('/',1)[-1]])
            return self.respond({},404)
    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    server.calls, server.mode, server.favorite = [], 'normal', True
    def item(name,index,kind):
        root = '/media/Movies' if kind == 'Movie' else '/media/TV'
        return {'Id':kind+str(index),'Type':kind,'Name':name,
            'Path':root+'/'+name+('/video.mkv' if kind == 'Movie' else ''),
            'Tags':['not-at-all'], 'UserData':{'Played':True,'PlayCount':1,'IsFavorite':False},
            'private':'synthetic-private-response'}
    names = {'Movies':[f'Movie {i:03}' for i in range(129)],'TV':['Show A','Show B']}
    server.items = {kind:[item(name,i,kind) for i,name in enumerate(names[library])]
        for library,kind in (('Movies','Movie'),('TV','Series'))}
    server.catalogs = {resource:[{'id':i+1,'path':'/media/'+library+'/'+name,'monitored':True}
        for i,name in enumerate(names[library])] for library,resource in (('Movies','movie'),('TV','series'))}
    inventory = [LibraryInventory(library,tuple((stage,'/media/'+library+suffix) for stage,suffix in
        (('Waiting',''),('Holding','_hold'),('Keep','_keep'),('Removal','_removal'))),
        tuple(InventoryTitle(name,'Waiting',30) for name in names[library]),True) for library in names]
    snapshot = {key:{} for key in ('first_seen','queued','in_removal','keep_seen','arr_sync_pending')}
    snapshot['first_seen'] = {('TV/' if lib == 'TV' else '')+name:'2026-01-01T01:02:03'
        for lib,rows in names.items() for name in rows}
    snapshot['extension'] = {'private':'synthetic-private-state'}
    base = 'http://127.0.0.1:'+str(server.server_port)
    settings = {'JELLYFIN_HOST_URL':base,'JELLYFIN_API_TOKEN':'synthetic-jellyfin-token',
        'RADARR_URL':base,'RADARR_API_KEY':'synthetic-arr-token',
        'SONARR_URL':base,'SONARR_API_KEY':'synthetic-arr-token'}
    thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    try: yield server, snapshot, inventory, settings
    finally: server.shutdown(); server.server_close(); thread.join()


def collect(services, **changes):
    server,snapshot,inventory,settings = services
    return collect_readonly_plan(snapshot=snapshot,inventories=inventory,settings=settings,now=NOW,**changes)


def test_actual_gets_paginate_all_users_and_preserve_second_user_favorites(services):
    server,snapshot,inventory,settings = services
    before = deepcopy((snapshot,inventory,settings))
    result = collect(services)
    assert result['scanned_titles'] == len(result['decisions']) == 131
    assert [(row.library,row.media_key,row.destination) for row in result['moves']] == [
        ('Movies','Movie 000','Keep'),('TV','TV/Show A','Keep')]
    # Each user's second movie page is fetched, even though only one move fits.
    assert sum('StartIndex=100' in path for _,path in server.calls) == 2
    assert sum(path == '/api/v3/movie' for _,path in server.calls) == 1
    assert sum(path == '/api/v3/series' for _,path in server.calls) == 1
    assert all(method == 'GET' for method,_ in server.calls)
    assert (snapshot,inventory,settings) == before
    assert 'synthetic-private' not in str(result) and 'synthetic-arr-token' not in str(result)
    assert not result['freshness_verified'] and not result['inventory_independently_verified']
    assert not result['media_actions_authorized']


@pytest.mark.parametrize('mode', ['sonarr_failure','tv_jf_failure'])
def test_failed_service_blocks_affected_library_without_retry(services,mode):
    server,*_ = services; server.mode = mode
    result = collect(services)
    assert [row.library for row in result['moves']] == ['Movies']
    tv = next(row for row in result['library_status'] if row['library'] == 'TV')
    assert not tv['arr_complete' if mode == 'sonarr_failure' else 'jellyfin_complete']
    assert sum(path == '/api/v3/series' for _,path in server.calls) == 1
    assert 'synthetic-private' not in str(result)


@pytest.mark.parametrize('change,reason', [('missing','arr_record_missing'),
    ('wrong_path','arr_path_conflict'),('duplicate','arr_record_ambiguous')])
def test_unmanaged_or_conflicting_title_skips_to_next_eligible(services,change,reason):
    server,*_ = services
    if change == 'missing': server.catalogs['movie'].pop(0)
    elif change == 'wrong_path': server.catalogs['movie'][0]['path'] = '/else/Movie 000'
    else: server.catalogs['movie'].append({'id':999,'path':'/else/Movie 000','monitored':True})
    result = collect(services)
    assert result['moves'][0].media_key == 'Movie 001'
    assert result['decisions'][0].reason == reason


def test_changing_page_total_never_returns_partial_movie_proposals(services):
    server,*_ = services; server.mode = 'bad_pagination'
    result = collect(services)
    assert [row.library for row in result['moves']] == ['TV']
    assert not result['library_status'][0]['jellyfin_complete']


def test_unmatched_jellyfin_title_never_becomes_unprotected(services):
    server,*_ = services; server.items['Series'].pop(0)
    result = collect(services)
    assert result['decisions'][129].reason == 'jellyfin_unavailable'
    assert result['moves'][-1].media_key == 'TV/Show B'


def test_invalid_identity_and_pending_state_refuse_before_any_http(services):
    server,snapshot,inventory,settings = services
    snapshot['legacy_pending_operations'] = {'kind':'move'}
    with pytest.raises(RuntimeError): collect(services)
    assert not server.calls


def test_deadline_never_returns_partial_plan(services):
    server,*_ = services
    ticks = iter([0,2])
    with pytest.raises(RuntimeError): collect(services,timer=lambda:next(ticks),maximum_seconds=1)
    assert not server.calls


def test_later_user_failure_discards_earlier_user_clearance(services):
    server,*_ = services; server.mode = 'second_user_failure'
    result = collect(services)
    assert [row.library for row in result['moves']] == ['TV']
    assert not result['library_status'][0]['jellyfin_complete']


def test_new_scan_does_not_reuse_prior_favorite_signals(services):
    server,*_ = services
    assert collect(services)['moves'][0].destination == 'Keep'
    server.favorite = False
    assert collect(services)['moves'][0].destination == 'Holding'
    assert sum(path == '/api/v3/movie' for _,path in server.calls) == 2


def test_settings_are_detached_before_first_request(services):
    from app.jellyfin_transport import ScheduledJellyfinGET
    server,snapshot,inventory,settings = services
    def factory(**kwargs):
        settings['FAVORITES_TRIGGER_KEEP'] = 'false'
        settings['RADARR_API_KEY'] = 'changed-private-token'
        return ScheduledJellyfinGET(**kwargs)
    result = collect(services,jellyfin_factory=factory)
    assert result['moves'][0].destination == 'Keep'
    assert result['library_status'][0]['arr_complete']


@pytest.mark.parametrize('limit', [0, True, float('inf'), 3601])
def test_invalid_collection_deadline_refuses_before_requests(services,limit):
    server,*_ = services
    with pytest.raises(ValueError): collect(services,maximum_seconds=limit)
    assert not server.calls


def test_progress_counts_collection_without_private_title_data(services):
    from app.scan_progress import observe
    rows=[]
    with observe(rows.append):
        result=collect(services)
    assert result['scanned_titles']==131
    assert rows[-1]['phase']=='planning'
    assert rows[-1]['checked']==rows[-1]['total']==131
    assert {row['library'] for row in rows} >= {'Movies','TV'}
    assert all(set(row)=={'phase','label','checked','total','library'} for row in rows)
