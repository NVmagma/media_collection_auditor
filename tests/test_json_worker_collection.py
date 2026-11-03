"""Real checked inventory feeds clock changes under the worker's existing lock."""
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path

import pytest
from app.json_readonly_scan import collect_worker_scan, rehearse_scan
from app.json_tracking_store import JsonTrackingStore
from test_json_readonly_scan import local, fake_collect, NOW


def test_discovery_and_episode_reset_are_saved_before_service_collection(local):
    source,values,movie,show,episode=local
    (movie.parent/'New').mkdir()
    stamp=datetime(2026,1,10).timestamp(); os.utime(episode,(stamp,stamp))
    before=json.loads(source.read_bytes()); seen=[]
    def collect(**kwargs):
        seen.append(deepcopy(kwargs['snapshot']))
        assert json.loads(source.read_bytes()) == kwargs['snapshot']
        return fake_collect(**kwargs)
    with JsonTrackingStore(source).session() as session:
        result=collect_worker_scan(session,settings=values,now=NOW,collect=collect)
    assert result['clock_changes_applied'] == 2 and result['tracking_modified']
    assert not result['comparison_only'] and not result['media_actions_authorized']
    expected=deepcopy(before)
    expected['first_seen'].update(New=NOW.isoformat())
    expected['first_seen']['TV/Show']='2026-01-10T00:00:00'
    assert seen == [expected] and json.loads(source.read_bytes()) == expected
    assert episode.is_file() and (movie/'movie.mkv').is_file()


def test_incomplete_library_never_saves_partial_discovery(local):
    source,values,movie,*_=local
    (movie.parent/'New').mkdir(); Path(values['RADARR_HOLDING_PATH']).rmdir()
    before=source.read_bytes()
    with JsonTrackingStore(source).session() as session:
        result=collect_worker_scan(session,settings=values,now=NOW,collect=fake_collect)
    assert result['clock_changes_applied'] == 0 and source.read_bytes() == before


def test_future_content_never_becomes_a_reset(local):
    source,values,_,_,episode=local
    stamp=datetime(2098,1,1).timestamp(); os.utime(episode,(stamp,stamp))
    before=source.read_bytes()
    with JsonTrackingStore(source).session() as session:
        result=collect_worker_scan(session,settings=values,now=NOW,collect=fake_collect)
    assert result['clock_changes_applied'] == 0 and source.read_bytes() == before
    assert next(row for row in result['decisions'] if row.library == 'TV').reason == 'future_content_timestamp'


def test_rehearsal_cannot_select_worker_checkpoint_mode(local):
    source,values,*_=local; before=source.read_bytes()
    with pytest.raises(TypeError):
        rehearse_scan(state_file=source,settings=values,_save_clocks=True)
    assert source.read_bytes() == before


def test_changed_inventory_before_checkpoint_saves_no_clock(local):
    source,values,movie,*_=local
    (movie.parent/'New').mkdir(); before=source.read_bytes()
    # The held descriptor observes a replacement before collection can save dates.
    from app import json_clock_updates
    apply=json_clock_updates.apply_clock_observations
    from unittest.mock import patch
    def changed(session,**kwargs):
        (movie.parent/'New').rename(movie.parent/'Replaced')
        return apply(session,**kwargs)
    with patch.object(json_clock_updates,'apply_clock_observations',changed):
        with pytest.raises((RuntimeError,OSError)):
            with JsonTrackingStore(source).session() as session:
                collect_worker_scan(session,settings=values,now=NOW,collect=fake_collect)
    assert source.read_bytes() == before
