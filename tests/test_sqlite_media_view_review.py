import json
import os
import sys
from pathlib import Path
import pytest
from app import sqlite_media_view_review as review

pytestmark=pytest.mark.skipif(sys.platform!='linux',reason='Linux held mount observation')


@pytest.fixture
def views(tmp_path):
    roots=[tmp_path/'shared',tmp_path/'native']
    for root in roots:
        root.mkdir()
        for stage in review.STAGES:(root/stage).mkdir()
        title=root/'Movies'/'private-title';title.mkdir();(title/'private-file.mkv').write_bytes(b'fixture')
    return dict(shared=roots[0],native=roots[1])


def test_matching_complete_metadata_is_redacted_and_never_an_execution_permit(views):
    result=review.compare_media_views(**views)
    assert result['status']=='media_views_observed' and result['all_stage_metadata_matches']
    assert result['native_stages_one_mount_and_device']
    assert not result['byte_equality_verified'] and not result['mount_change_authorized']
    assert 'private-title' not in json.dumps(result) and 'private-file' not in json.dumps(result)


def test_equal_top_level_counts_do_not_hide_different_title_names(views):
    (views['native']/'Movies'/'private-title').rename(views['native']/'Movies'/'different-title')
    result=review.compare_media_views(**views)
    assert not result['all_stage_metadata_matches']
    assert result['stages'][0]['shared_titles']==result['stages'][0]['native_titles']==1


def test_matching_title_names_do_not_hide_missing_nested_media(views):
    (views['native']/'Movies'/'private-title'/'private-file.mkv').unlink()
    assert not review.compare_media_views(**views)['all_stage_metadata_matches']


@pytest.mark.parametrize('kind',['symlink','missing_stage','limit','same_root'])
def test_unsafe_or_incomplete_observations_block(views,kind):
    if kind=='symlink':(views['native']/'Movies'/'link').symlink_to('/etc')
    elif kind=='missing_stage':(views['native']/'TV').rmdir()
    elif kind=='limit':views['maximum_entries']=1
    else:views['native']=views['shared']
    assert review.compare_media_views(**views)['status']=='media_view_review_blocked'


def test_concurrent_change_invalidates_entire_observation(views):
    count=0
    def timer():
        nonlocal count
        count+=1
        if count==45:(views['shared']/'Movies'/'private-title'/'private-file.mkv').write_bytes(b'changed')
        return count/10000
    result=review.compare_media_views(**views,timer=timer)
    assert result['status']=='media_view_review_blocked' or not result['all_stage_metadata_matches']
