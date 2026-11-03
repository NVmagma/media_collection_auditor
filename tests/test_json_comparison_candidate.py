"""Offline JSON candidates retain latest clocks without activating a worker."""
import json
from pathlib import Path

import pytest
from scripts import json_comparison_candidate as candidate
from scripts import unraid_live_update_backup as backup
from test_unraid_live_update_backup import options, fingerprint


def setup(tmp_path):
    packet, state, inputs, values, control = options(tmp_path)
    state['future_extension'] = {'private': 'retained exactly'}
    backup.capture_backup(**values)
    parent = tmp_path/'comparison'; parent.mkdir(mode=0o700)
    kwargs = dict(backup=packet, backup_identity=values['expected_identity'],
        fingerprint=fingerprint(packet), parent=parent)
    return packet, state, parent, kwargs


def test_preserves_latest_snapshot_unknowns_and_claims_without_touching_source(tmp_path):
    packet, state, parent, kwargs = setup(tmp_path)
    before = {p: p.read_bytes() for p in packet.iterdir()}
    root, report = candidate.prepare_candidate(**kwargs)
    assert root.parent == parent
    assert (root/'auditor_state.json').read_bytes() == before[packet/'tracking-snapshot.json']
    assert json.loads((root/'auditor_state.json').read_bytes()) == state
    assert (root/'scan-claims-archive.json').read_bytes() == before[packet/'daily-claims.json']
    assert all(p.read_bytes() == raw for p, raw in before.items())
    assert report['source_snapshot_revision'] == 17
    assert report['worker_configured'] is False and report['media_actions_authorized'] is False
    assert 'retained exactly' not in json.dumps(report)
    assert root.stat().st_mode & 0o777 == 0o700
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in root.iterdir())
    second, _ = candidate.prepare_candidate(**kwargs)
    assert second != root  # A new candidate never overwrites an existing one.


@pytest.mark.parametrize('change', ['corrupt', 'fingerprint', 'partial', 'overlap'])
def test_bad_or_partial_backup_does_not_create_candidate(tmp_path, change):
    packet, _, parent, kwargs = setup(tmp_path)
    if change == 'corrupt': (packet/'tracking-snapshot.json').write_bytes(b'{}')
    elif change == 'fingerprint': kwargs['fingerprint'] = '0'*64
    elif change == 'partial': (packet/'backup-complete.json').unlink()
    else: kwargs['parent'] = packet
    with pytest.raises((ValueError, RuntimeError, OSError)):
        candidate.prepare_candidate(**kwargs)
    assert list(parent.iterdir()) == []


def test_interrupted_candidate_has_no_completion_and_is_not_replayed(tmp_path, monkeypatch):
    _, _, parent, kwargs = setup(tmp_path)
    original = candidate._write
    def fail(directory, name, raw):
        if name == 'scan-claims-archive.json': raise OSError('synthetic interruption')
        original(directory, name, raw)
    monkeypatch.setattr(candidate, '_write', fail)
    with pytest.raises(OSError): candidate.prepare_candidate(**kwargs)
    partial, = parent.iterdir()
    assert (partial/'auditor_state.json').exists()
    assert not (partial/'comparison-complete.json').exists()
    monkeypatch.setattr(candidate, '_write', original)
    root, _ = candidate.prepare_candidate(**kwargs)
    assert root != partial and not (partial/'comparison-complete.json').exists()
