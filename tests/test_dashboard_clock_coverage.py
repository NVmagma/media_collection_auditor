from copy import deepcopy
import json
from scripts.dashboard_clock_coverage import coverage


def test_exact_case_missing_and_other_stage_clocks_are_distinguished(tmp_path):
    media=tmp_path/'media'
    for name in ('Exact','Lower','Untracked','OtherStage','Invalid'):(media/'Movies'/name).mkdir(parents=True)
    for name in ('Movies_hold','Movies_keep','Movies_removal'):(media/name).mkdir()
    state={'first_seen':{'Exact':'2026-10-01T11:30:00','lower':'2026-10-02','Invalid':'private-bad-clock'},
        'queued':{'OtherStage':'2026-10-03'},'private':{'secret':'never-output'}}
    before=deepcopy(state)
    report=coverage(state,{'MEDIA_PATH':str(media),'ENABLE_TV':'false'})
    waiting=report['libraries'][0]
    assert waiting['recorded_dates']==1 and waiting['invalid_dates']==1
    assert waiting['missing_dates']==3 and waiting['case_only_candidates']==1
    assert waiting['records_in_other_stages']==1 and waiting['unmatched_tracking_records']==1
    assert state==before
    assert all(value not in json.dumps(report) for value in ('Exact','OtherStage','private-bad-clock',str(media),'never-output'))


def test_unavailable_directory_is_never_reported_as_empty_success(tmp_path):
    report=coverage({}, {'MEDIA_PATH':str(tmp_path),'ENABLE_TV':'false'})
    assert all(row['status']=='directory_unavailable' for row in report['libraries'])


def test_tv_and_movie_keys_remain_separate(tmp_path):
    for library in ('Movies','TV'):
        for suffix in ('','_hold','_keep','_removal'):(tmp_path/(library+suffix)).mkdir()
        (tmp_path/library/'Same').mkdir()
    report=coverage({'first_seen':{'TV/Same':'2026-10-01'}},
        {'MEDIA_PATH':str(tmp_path),'ENABLE_TV':'true'})
    waiting={row['library']:row for row in report['libraries'] if row['stage']=='Waiting'}
    assert waiting['Movies']['missing_dates']==1 and waiting['TV']['recorded_dates']==1
