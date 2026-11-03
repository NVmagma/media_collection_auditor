"""Disposable local filesystem + JSON rehearsal; no production roots or writes."""
from dataclasses import replace
from datetime import datetime
import json
import os
from pathlib import Path

import pytest
from app.json_readonly_scan import rehearse_scan
from app.json_scan_collection import collect_readonly_plan
from app.json_lifecycle_plan import plan_scan, LibraryObservation, TitleObservation
from test_json_tracking_store import state

NOW = datetime(2026,1,20,12)
SIG = dict(played=True,favorite=False,disliked=True,keep=False,keep_all=False,protected=False)


@pytest.fixture
def local(tmp_path):
    values = {'ENABLE_MOVIES':'true','ENABLE_TV':'true','TV_NEW_EPISODES_RESET_CLOCK':'true'}
    for prefix,lib in (('RADARR','Movies'),('SONARR','TV')):
        for stage,field,suffix in (('Waiting','TRANSIENT',''),('Holding','HOLDING','_hold'),('Keep','KEEP','_keep'),('Removal','REMOVAL','_removal')):
            path = tmp_path/(lib+suffix); path.mkdir()
            values[prefix+'_'+field+'_PATH'] = str(path)
    movie = Path(values['RADARR_TRANSIENT_PATH'])/'Movie'; movie.mkdir(); (movie/'movie.mkv').write_bytes(b'disposable')
    show = Path(values['SONARR_TRANSIENT_PATH'])/'Show'; show.mkdir()
    season = show/'Season 1'; season.mkdir(); episode = season/'one.mkv'; episode.write_bytes(b'disposable')
    stamp = datetime(2025,12,1).timestamp()
    os.utime(episode,(stamp,stamp)); os.utime(season,(stamp,stamp))
    source = tmp_path/'state.json'; source.write_text(json.dumps(state()))
    return source,values,movie,show,episode


def fake_collect(**kwargs):
    libraries=[]
    for lib in kwargs['inventories']:
        rows = tuple(TitleObservation(('TV/' if lib.library == 'TV' else '')+row.folder,
            row.stage,row.threshold_days,dict(SIG),'exact_source_match',row.blocker) for row in lib.titles)
        libraries.append(LibraryObservation(lib.library,lib.complete,lib.complete,rows))
    return plan_scan(snapshot=kwargs['snapshot'],libraries=libraries,now=kwargs['now'])


def run(local,**kwargs):
    source,values,*_ = local
    return rehearse_scan(state_file=source,settings=values,now=NOW,collect=fake_collect,**kwargs)


def test_roots_and_titles_checked_no_clock_or_media_changes(local):
    source,values,movie,show,episode = local
    raw = source.read_bytes(); media = episode.read_bytes(),episode.stat().st_mtime_ns
    result = run(local)
    assert [row.media_key for row in result['moves']] == ['Movie','TV/Show']
    assert result['inventory_checked_before_and_after'] and not result['tracking_modified']
    assert not result['external_writers_excluded'] and not result['media_actions_authorized']
    assert source.read_bytes() == raw and (episode.read_bytes(),episode.stat().st_mtime_ns) == media


def test_new_episode_proposes_reset_and_blocks_old_clock_move(local):
    source,values,movie,show,episode = local
    stamp = datetime(2026,1,10).timestamp(); os.utime(episode,(stamp,stamp))
    before = source.read_bytes()
    result = run(local)
    assert [row.media_key for row in result['moves']] == ['Movie']
    row = next(row for row in result['decisions'] if row.media_key == 'TV/Show')
    assert row.reason == 'content_reset_required'
    assert result['clock_proposals'][0]['proposed'] == '2026-01-10T00:00:00'
    assert source.read_bytes() == before


def test_future_episode_skips_only_show_without_reset_proposal(local):
    source,values,movie,show,episode = local
    stamp = datetime(2098,1,1).timestamp(); os.utime(episode,(stamp,stamp))
    before = source.read_bytes()
    result = run(local)
    assert [row.media_key for row in result['moves']] == ['Movie']
    assert result['decisions'][-1].reason == 'future_content_timestamp'
    assert not result['clock_proposals'] and source.read_bytes() == before


def test_symlink_episode_is_not_followed_and_blocks_only_title(local):
    source,values,movie,show,episode = local
    episode.unlink(); episode.symlink_to(movie/'movie.mkv')
    stamp = datetime(2025,12,1).timestamp(); os.utime(episode.parent,(stamp,stamp))
    result = run(local)
    assert result['decisions'][-1].reason == 'content_unavailable'
    assert [row.library for row in result['moves']] == ['Movies']


def test_missing_stage_blocks_affected_library(local):
    source,values,*_ = local
    Path(values['SONARR_HOLDING_PATH']).rmdir()
    result = run(local)
    assert [row.library for row in result['moves']] == ['Movies']


def test_known_housekeeping_is_ignored_without_removing_it(local):
    source,values,*_ = local
    marker = Path(values['SONARR_TRANSIENT_PATH'])/'.DS_Store'; marker.write_bytes(b'finder')
    trash = marker.parent/'.deletedByTMM'; trash.mkdir()
    result = run(local)
    assert result['ignored_housekeeping_entries'] == 2
    assert marker.read_bytes() == b'finder' and trash.is_dir()
    assert result['scanned_titles'] == 2


def test_new_folder_reports_discovery_without_backdating(local):
    source,values,*_ = local
    (Path(values['RADARR_TRANSIENT_PATH'])/'New').mkdir()
    before = source.read_bytes()
    result = run(local)
    assert result['clock_proposals'] == ({'library':'Movies','title':'New','stage':'Waiting',
        'reason':'discovery_required','previous':None,'proposed':NOW.isoformat()},)
    assert source.read_bytes() == before


def test_root_alias_refused_before_collection(local):
    source,values,*_ = local
    values['SONARR_HOLDING_PATH'] = values['SONARR_KEEP_PATH']
    with pytest.raises(ValueError): run(local)


def test_title_added_during_service_reads_invalidates_rehearsal(local):
    source,values,*_ = local
    def change(**kwargs):
        (Path(values['RADARR_TRANSIENT_PATH'])/'Late').mkdir()
        return fake_collect(**kwargs)
    with pytest.raises(RuntimeError): rehearse_scan(state_file=source,settings=values,now=NOW,collect=change)


def test_nested_episode_changed_during_reads_invalidates_rehearsal(local):
    source,values,movie,show,episode = local
    def change(**kwargs):
        stamp = datetime(2026,1,10).timestamp(); os.utime(episode,(stamp,stamp))
        return fake_collect(**kwargs)
    with pytest.raises(RuntimeError): rehearse_scan(state_file=source,settings=values,now=NOW,collect=change)


def test_configured_remote_alias_used_for_collection(local):
    source,values,*_ = local
    values['SONARR_APP_HOLDING_PATH'] = '/arr/TV_hold'
    def collect(**kwargs):
        tv = next(lib for lib in kwargs['inventories'] if lib.library == 'TV')
        assert dict(tv.roots)['Holding'] == '/arr/TV_hold'
        return fake_collect(**kwargs)
    rehearse_scan(state_file=source,settings=values,now=NOW,collect=collect)


def test_actual_loopback_services_with_descriptor_checked_local_inventory(local,services):
    # Reuse the real GET fixture with paths adjusted to these disposable roots.
    server,snapshot,inventories,remote_settings = services
    source,values,movie,show,episode = local
    values.update(remote_settings)
    server.items['Movie'] = [{**server.items['Movie'][0], 'Path':str(movie/'movie.mkv')}]
    server.items['Series'] = [{**server.items['Series'][0], 'Path':str(show)}]
    server.catalogs['movie'] = [{'id':1,'path':str(movie),'monitored':True}]
    server.catalogs['series'] = [{'id':2,'path':str(show),'monitored':True}]
    before = source.read_bytes()
    result = rehearse_scan(state_file=source,settings=values,now=NOW)
    assert len(result['moves']) == 2 and source.read_bytes() == before
    assert all(method == 'GET' for method,_ in server.calls)


from test_json_scan_collection import services


def test_missing_stage_reports_fixed_actionable_issue(local):
    source,values,*_ = local
    Path(values['SONARR_HOLDING_PATH']).rmdir()
    result = run(local)
    assert result['inventory_issues'] == ({'library':'TV','stage':'Holding',
        'reason':'stage_unavailable_or_changed'},)
    assert str(source.parent) not in str(result['inventory_issues'])


def test_pending_intent_stops_before_any_media_inventory(local,monkeypatch):
    import app.json_readonly_scan as module
    source,values,*_ = local
    value = json.loads(source.read_bytes()); value['sqlite_pending_operations'] = {'kind':'arr_sync'}
    source.write_text(json.dumps(value))
    monkeypatch.setattr(module,'_open_directory',lambda *a: pytest.fail('No media enumeration before pending check'))
    with pytest.raises(RuntimeError): run(local)


def test_content_reset_uses_captured_lifecycle_timezone(local):
    from zoneinfo import ZoneInfo
    source,values,movie,show,episode = local
    values['SQLITE_DAILY_RUN_TIMEZONE'] = 'America/Los_Angeles'
    observed = datetime(2026,1,10,3,tzinfo=ZoneInfo('America/Los_Angeles'))
    os.utime(episode,(observed.timestamp(),observed.timestamp()))
    result = run(local)
    assert result['lifecycle_timezone'] == 'America/Los_Angeles'
    assert result['clock_proposals'][0]['proposed'] == '2026-01-10T03:00:00'


@pytest.mark.parametrize('explicit', ['absent','empty'])
def test_media_path_defaults_match_existing_application(local,explicit):
    source,values,*_ = local
    expected = run(local)
    values['MEDIA_PATH'] = str(source.parent)
    for prefix in ('RADARR','SONARR'):
        for field in ('TRANSIENT','HOLDING','KEEP','REMOVAL'):
            key = prefix+'_'+field+'_PATH'
            if explicit == 'absent': values.pop(key)
            else: values[key] = ''
    result = run(local)
    assert result['moves'] == expected['moves'] and result['scanned_titles'] == expected['scanned_titles']


def test_existing_case_insensitive_boolean_settings_are_supported(local):
    source,values,*_ = local
    values.update(ENABLE_TV='True',TV_NEW_EPISODES_RESET_CLOCK=' TRUE ')
    assert run(local)['scanned_titles'] == 2
