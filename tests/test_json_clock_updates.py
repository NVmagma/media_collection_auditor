"""Verified clock checkpoints preserve every unrelated field and scan budget."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
import json

import pytest
from app.json_clock_updates import ClockObservation, apply_clock_observations
from app.json_scan_control import KEY, initialize_control
from test_json_tracking_store import store

NOW = datetime(2026,1,20,12)


def discovery(): return ClockObservation('New','Waiting',None,NOW,'discovered')
def reset(): return ClockObservation('TV/Show','Waiting','2026-01-02T02:03:04',datetime(2026,1,10),'content_reset')


def test_verified_discovery_and_tv_reset_are_one_checkpoint_without_moves(store):
    before = json.loads(store.path.read_bytes())
    with store.session() as session:
        seen=[]
        result = apply_clock_observations(session,changes=[discovery(),reset()],now=NOW,
            verify_change=lambda change: seen.append(change.media_key) is None)
        assert seen == ['New','TV/Show']
    expected = deepcopy(before); expected['first_seen'].update(New=NOW.isoformat())
    expected['first_seen']['TV/Show'] = '2026-01-10T00:00:00'
    assert json.loads(store.path.read_bytes()) == expected
    assert result['changed_dates'] == 2 and result['arr_updates_sent'] == 0
    assert not result['media_actions_performed'] and not result['scan_claims_modified']


def test_later_failed_evidence_never_saves_earlier_clock(store):
    raw = store.path.read_bytes()
    with pytest.raises(RuntimeError):
        with store.session() as session:
            apply_clock_observations(session,changes=[discovery(),reset()],now=NOW,
                verify_change=lambda change: change.media_key == 'New')
    assert store.path.read_bytes() == raw


@pytest.mark.parametrize('change',[replace(discovery(),observed_at=datetime(2020,1,1)),
    replace(discovery(),media_key='Movie'), replace(reset(),previous='2025-01-01'),
    replace(reset(),observed_at=datetime(2025,1,1)), replace(reset(),media_key='Movie'),
    replace(reset(),observed_at=datetime(2098,1,1))])
def test_stale_backdated_future_or_wrong_identity_never_calls_verifier(store,change):
    raw = store.path.read_bytes()
    with pytest.raises((RuntimeError,ValueError)):
        with store.session() as session:
            apply_clock_observations(session,changes=[change],now=NOW,
                verify_change=lambda _:pytest.fail('Invalid proposal must not read services'))
    assert store.path.read_bytes() == raw


def test_duplicate_changes_and_conflicting_stages_refuse_before_verification(store):
    raw = store.path.read_bytes()
    with pytest.raises(ValueError):
        with store.session() as session:
            apply_clock_observations(session,changes=[discovery(),discovery()],now=NOW,verify_change=lambda _:True)
    assert store.path.read_bytes() == raw


def test_cooldown_metadata_and_unknown_fields_remain_unchanged(store):
    from datetime import timezone
    with store.session() as session:
        initialize_control(session,previous_started_at=NOW.replace(tzinfo=timezone.utc))
    before = json.loads(store.path.read_bytes())
    with store.session() as session:
        apply_clock_observations(session,changes=[discovery()],now=NOW,verify_change=lambda _:True)
    current = json.loads(store.path.read_bytes())
    assert current[KEY] == before[KEY] and current['unknown'] == before['unknown']


def test_intervening_file_replacement_retains_external_state(store):
    def replace_source(_):
        other = store.path.with_name('other.json'); other.write_bytes(store.path.read_bytes())
        other.replace(store.path)
        return True
    with pytest.raises(RuntimeError):
        with store.session() as session:
            apply_clock_observations(session,changes=[discovery()],now=NOW,verify_change=replace_source)
    assert 'New' not in json.loads(store.path.read_bytes())['first_seen']
