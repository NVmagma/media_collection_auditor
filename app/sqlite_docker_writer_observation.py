"""Strict selected-writer observation checks; never an ownership permit.

A stopped Docker observation does not exclude host/share writers, open handles,
prior streams, administrative bypasses or a subsequent state change.
"""
import re


def require_stopped_writer(observation, expected_id):
    """Reject ambiguous daemon observations without returning sensitive metadata."""
    if not isinstance(expected_id, str) or not re.fullmatch(r'[0-9a-f]{64}', expected_id):
        raise ValueError('Full selected container ID required')
    if not isinstance(observation, dict) or observation.get('Id') != expected_id:
        raise ValueError('Selected writer identity unverified')
    state = observation.get('State')
    host = observation.get('HostConfig')
    if not isinstance(state, dict) or not isinstance(host, dict):
        raise ValueError('Selected writer state unverified')
    if (any(state.get(key) is not False for key in ('Running', 'Paused', 'Restarting', 'Dead'))
            or state.get('Status') != 'exited'
            or type(state.get('Pid')) is not int or state['Pid'] != 0):
        raise ValueError('Selected writer not conclusively stopped')
    policy = host.get('RestartPolicy')
    if (not isinstance(policy, dict) or policy.get('Name') != 'no'
            or type(policy.get('MaximumRetryCount')) is not int
            or policy['MaximumRetryCount'] != 0):
        raise ValueError('Selected writer restart policy unverified')
