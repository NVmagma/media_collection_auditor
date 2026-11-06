from datetime import datetime, timedelta, timezone
import json
import sys
from types import SimpleNamespace

import pytest

from app import tv_season_move
from app.json_scan_control import KEY, ScanAttempt, admission_status, initialize_control
from app.json_tracking_store import JsonTrackingStore
from app.tv_season_move import ARCHIVE, move_season
from app.tv_season_policy import SeasonPlan

pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='Linux atomic rename required')


@pytest.fixture
def season_move(tmp_path):
    active = tmp_path / 'active' / 'Example'
    holding = tmp_path / 'holding' / 'Example'
    active.mkdir(parents=True)
    holding.mkdir(parents=True)
    (active / 'Season 01').mkdir()
    (active / 'Season 01' / 'episode.mkv').write_bytes(b'fixture')
    state_file = tmp_path / 'state.json'
    state_file.write_text(json.dumps({section: {} for section in
                                      ('first_seen', 'queued', 'in_removal', 'keep_seen', 'arr_sync_pending')}))
    store = JsonTrackingStore(state_file)
    now = datetime.now(timezone.utc)
    with store.session() as session:
        initialize_control(session, previous_started_at=now - timedelta(hours=2))
        session.state[KEY]['last_result'] = 'running'
        session.checkpoint()
    monitoring = [True]
    updates = []

    def set_monitoring(value, *, expected):
        assert monitoring[0] is expected
        updates.append(value)
        monitoring[0] = value

    def execute(restore=False):
        plan = SeasonPlan(latest=2, restore=(1,)) if restore else SeasonPlan(latest=2, stage=(1,))
        with store.session() as session:
            move_season(ScanAttempt(session), title='Example', season=1, name='Season 01',
                        active_parent=str(active), holding_parent=str(holding), restore=restore,
                        read_plan=lambda: plan,
                        monitoring=SimpleNamespace(season=1, series_id=17, source_path='/media/TV/Example',
                                                   endpoint_identity='a' * 64,
                                                   read=lambda: monitoring[0], set=set_monitoring))

    return active, holding, state_file, updates, execute


def test_stage_and_restore_preserve_files_and_prior_monitoring(season_move):
    active, holding, state_file, updates, execute = season_move
    execute()
    saved = json.loads(state_file.read_bytes())
    assert saved[ARCHIVE]['TV/Example/1']['previous_monitoring'] is True
    assert saved[ARCHIVE]['TV/Example/1']['staged_at']
    assert saved[KEY]['journal'] is None
    assert (holding / 'Season 01' / 'episode.mkv').read_bytes() == b'fixture'
    assert not (active / 'Season 01').exists()
    execute(restore=True)
    assert updates == [False, True]
    assert (active / 'Season 01' / 'episode.mkv').read_bytes() == b'fixture'
    assert json.loads(state_file.read_bytes())[ARCHIVE] == {}


@pytest.mark.parametrize("folder", ["Season 01", "Season 1"])
def test_destination_collision_blocks_before_any_write(season_move, folder):
    active, holding, state_file, updates, execute = season_move
    (holding / folder).mkdir()
    before = state_file.read_bytes()
    with pytest.raises(RuntimeError, match='occupied'):
        execute()
    assert state_file.read_bytes() == before
    assert updates == []
    assert (active / 'Season 01' / 'episode.mkv').is_file()


def test_interrupted_rename_retains_intent_and_blocks_scan(season_move, monkeypatch):
    active, holding, state_file, updates, execute = season_move
    rename = tv_season_move.rename_directory_noreplace_at

    def interrupted(*args):
        rename(*args)
        raise OSError('simulated interruption after rename')

    monkeypatch.setattr(tv_season_move, 'rename_directory_noreplace_at', interrupted)
    with pytest.raises(OSError, match='simulated interruption'):
        execute()
    state = json.loads(state_file.read_bytes())
    assert state[KEY]['journal']['kind'] == 'tv_season_move'
    assert admission_status(state, now=datetime.now(timezone.utc))['status'] == 'review_required'
    assert updates == [False]
    assert not (active / 'Season 01').exists()
    assert (holding / 'Season 01' / 'episode.mkv').is_file()



@pytest.mark.parametrize('restore', [False, True])
def test_completed_interruption_can_be_acknowledged_without_replay(season_move, monkeypatch, restore):
    from app.tv_season_recovery import recover_season

    active, holding, state_file, updates, execute = season_move
    if restore:
        execute()
    original_finish = ScanAttempt.finish_operation

    def interrupted(*args, **kwargs):
        raise OSError('simulated crash before the final checkpoint')

    monkeypatch.setattr(ScanAttempt, 'finish_operation', interrupted)
    with pytest.raises(OSError, match='simulated crash'):
        execute(restore=restore)
    monkeypatch.setattr(ScanAttempt, 'finish_operation', original_finish)
    before = state_file.read_bytes()
    calls = []

    def factory(**kwargs):
        assert kwargs['series_id'] == 17 and kwargs['season'] == 1
        def read():
            calls.append('GET')
            return updates[-1]
        return SimpleNamespace(endpoint_identity='a' * 64, read=read)

    store = JsonTrackingStore(state_file)
    kwargs = {'settings': {}, 'monitoring_factory': factory}
    review = recover_season(store, **kwargs)
    assert review['required_action'] == 'acknowledge_season_move'
    assert state_file.read_bytes() == before
    with pytest.raises(RuntimeError, match='review changed'):
        recover_season(store, expected='0' * 64, **kwargs)
    assert state_file.read_bytes() == before
    result = recover_season(store, expected=review['review_fingerprint'], **kwargs)
    assert result['restored'] is restore
    state = json.loads(state_file.read_bytes())
    assert state[KEY]['journal'] is None
    assert ('TV/Example/1' in state[ARCHIVE]) is not restore
    assert calls == ['GET'] * 6
    assert updates == ([False, True] if restore else [False])
    destination = active if restore else holding
    assert (destination / 'Season 01' / 'episode.mkv').read_bytes() == b'fixture'
