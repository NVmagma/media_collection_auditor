import copy
import pytest
from app.sqlite_docker_writer_observation import require_stopped_writer

IDENTITY = 'a' * 64


def stopped():
    return {'Id': IDENTITY, 'State': {'Running': False, 'Paused': False,
        'Restarting': False, 'Dead': False, 'Status': 'exited', 'Pid': 0},
        'HostConfig': {'RestartPolicy': {'Name': 'no', 'MaximumRetryCount': 0}}}


def test_complete_observation_is_read_only_and_grants_no_receipt():
    value = stopped()
    before = copy.deepcopy(value)
    assert require_stopped_writer(value, IDENTITY) is None
    assert value == before


@pytest.mark.parametrize('key,value', [('Running', True), ('Paused', True),
    ('Restarting', True), ('Dead', True), ('Status', 'created'), ('Status', 'removing'),
    ('Pid', 1), ('Pid', False), ('Running', 0), ('Paused', None)])
def test_uncertain_or_active_state_rejected(key, value):
    observed = stopped()
    observed['State'][key] = value
    with pytest.raises(ValueError, match='conclusively stopped'):
        require_stopped_writer(observed, IDENTITY)


@pytest.mark.parametrize('key', ['Running', 'Paused', 'Restarting', 'Dead', 'Status', 'Pid'])
def test_missing_state_never_defaults_to_stopped(key):
    observed = stopped()
    del observed['State'][key]
    with pytest.raises(ValueError):
        require_stopped_writer(observed, IDENTITY)


@pytest.mark.parametrize('policy', [None, {}, {'Name': 'always', 'MaximumRetryCount': 0},
    {'Name': 'no'}, {'Name': 'no', 'MaximumRetryCount': False},
    {'Name': 'no', 'MaximumRetryCount': 1}])
def test_restart_policy_requires_explicit_exact_types(policy):
    observed = stopped()
    observed['HostConfig']['RestartPolicy'] = policy
    with pytest.raises(ValueError, match='restart policy'):
        require_stopped_writer(observed, IDENTITY)


@pytest.mark.parametrize('expected,actual', [('a'*12, IDENTITY), (IDENTITY, 'b'*64),
    (IDENTITY, None)])
def test_identity_must_match_full_selected_id(expected, actual):
    observed = stopped()
    observed['Id'] = actual
    with pytest.raises(ValueError):
        require_stopped_writer(observed, expected)
