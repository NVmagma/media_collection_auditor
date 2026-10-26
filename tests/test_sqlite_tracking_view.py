"""Candidate widgets consume one revision, without JSON fallback or secret leakage."""
import json
from unittest.mock import patch

import pytest

from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_store import SQLiteStateStore
from app.sqlite_tracking_view import capture_candidate_tracking_view
import app.sqlite_tracking_view as module


def snapshot():
    return {'first_seen': {'A': '2024-01-01', 'TV/B': '2024-01-02'},
            'queued': {'C': '2024-01-03'}, 'keep_seen': {}, 'in_removal': {},
            'arr_sync_pending': {}, 'unknown': {'token': 'private-secret', 'path': '/private/path'}}


@pytest.fixture
def database(tmp_path):
    path = tmp_path / 'state.db'
    write_offline_snapshot(snapshot(), path)
    return path


def test_one_capture_drives_all_projections_and_detaches(database):
    original = module.read_experimental_sqlite_dashboard_snapshot
    with patch.object(module, 'read_experimental_sqlite_dashboard_snapshot', wraps=original) as capture:
        view = capture_candidate_tracking_view(database)
    assert capture.call_count == 1
    assert view['summary']['tracking_counts']['waiting'] == 2
    assert view['leaving_soon']['items'][0]['title'] == 'C'
    assert view['oldest_waiting']['items'][1]['library'] == 'TV'
    for key in ('summary', 'leaving_soon', 'oldest_waiting'):
        assert view[key]['state_revision'] == view['state_revision']
        assert view[key]['storage_authority'] == 'sqlite_candidate'
    assert 'private-secret' not in json.dumps(view)
    assert '/private/path' not in json.dumps(view)
    view['summary']['tracking_counts']['waiting'] = 100
    assert capture_candidate_tracking_view(database)['summary']['tracking_counts']['waiting'] == 2


def test_concurrent_checkpoint_rejects_whole_capture(database):
    original = module._project_tracking_status
    def change(capture):
        store = SQLiteStateStore(database)
        state, revision = store.load_with_revision()
        state['queued']['New'] = '2024-02-01'
        store.save_if_revision(state, revision)
        return original(capture)
    with patch.object(module, '_project_tracking_status', change):
        with pytest.raises(RuntimeError, match='unavailable'):
            capture_candidate_tracking_view(database)


def test_identical_database_replacement_is_rejected(database):
    original = module._project_tracking_status
    def replace(capture):
        payload = database.read_bytes()
        database.rename(database.with_name('old.db'))
        database.write_bytes(payload)
        return original(capture)
    with patch.object(module, '_project_tracking_status', replace):
        with pytest.raises(RuntimeError, match='unavailable'):
            capture_candidate_tracking_view(database)


def test_pending_presence_redacted_without_inferring_clearance(database):
    store = SQLiteStateStore(database)
    state, revision = store.load_with_revision()
    state['sqlite_pending_operations'] = {'credentials': 'private-secret'}
    store.save_if_revision(state, revision)
    report = capture_candidate_tracking_view(database)
    assert report['summary']['pending_operation_present'] is True
    assert report['production_authorized'] is False
    assert 'credentials' not in json.dumps(report)


@pytest.mark.parametrize('kind', ['missing', 'damaged', 'symlink', 'hardlink'])
def test_invalid_database_never_falls_back_to_json(tmp_path, kind):
    path = tmp_path / 'state.db'
    (tmp_path / 'state.json').write_text(json.dumps(snapshot()))
    if kind == 'damaged':
        path.write_bytes(b'not sqlite')
    elif kind in ('symlink', 'hardlink'):
        import os
        real = tmp_path / 'real.db'
        write_offline_snapshot(snapshot(), real)
        if kind == 'symlink':
            path.symlink_to(real)
        else:
            os.link(real, path)
    with pytest.raises(RuntimeError, match='^Candidate SQLite tracking view unavailable$'):
        capture_candidate_tracking_view(path)
    assert not path.exists() if kind == 'missing' else True


def test_invalid_hold_policy_rejects_whole_capture(database):
    with pytest.raises(RuntimeError, match='unavailable'):
        capture_candidate_tracking_view(database, holding_days=0)


def test_sqlite_tv_filter_preserves_global_summary_and_shared_revision(database):
    view=capture_candidate_tracking_view(database,library='TV')
    assert view['summary']['tracking_counts']['waiting']==2
    assert [item['title'] for item in view['oldest_waiting']['items']]==['B']
    assert view['leaving_soon']['items']==[]
    assert view['oldest_waiting']['state_revision']==view['summary']['state_revision']
