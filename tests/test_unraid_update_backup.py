from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import patch
import pytest
from scripts import unraid_update_backup as backup


def case(tmp_path):
    root = tmp_path / 'packet'; root.mkdir(mode=0o700)
    state = {key: {} for key in backup.SECTIONS}
    state['first_seen'] = {'Movies/Fixture': '2020-01-02T03:04:05', 'TV/Fixture': '2021-02-03T04:05:06'}
    state['unknown-extension'] = {'private': 'private-secret'}
    inputs = {name: (raw, (1, index)) for index, (name, raw) in enumerate((
        ('saved-config.json', b'{"token":"private-secret"}'),
        ('retained-source.json', b'{"private":"private-secret"}'),
        ('current-binding.json', b'{"private":"private-secret"}')))}
    options = dict(directory=root, expected_identity=(root.stat().st_dev, root.stat().st_ino),
        container={'Name': '/media_collection_auditor', 'Id': 'a'*64, 'Image': 'sha256:'+'b'*64,
                   'Config': {'Env': ['PRIVATE=private-secret']}}, template=b'<Container/>',
        source_revision='c'*40, validate_current=lambda: None,
        read_snapshot=lambda: (deepcopy(state), 0), read_inputs=lambda: deepcopy(inputs))
    return root, state, inputs, options


def test_backup_preserves_all_clocks_unknowns_settings_and_private_permissions(tmp_path):
    root, state, inputs, options = case(tmp_path)
    result = backup.capture_backup(**options)
    assert json.loads((root / 'tracking-snapshot.json').read_bytes()) == state
    assert (root / 'saved-config.json').read_bytes() == inputs['saved-config.json'][0]
    assert result['backup_kind'] == 'logical_tracking_and_settings'
    assert result['update_authorized'] is False and result['automatic_restoration'] is False
    assert 'private-secret' not in json.dumps(result)
    receipt = json.loads((root / 'backup-complete.json').read_bytes())
    for name in backup.FILES:
        assert receipt['sha256'][name] == hashlib.sha256((root/name).read_bytes()).hexdigest()
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in root.iterdir())


def test_existing_or_partial_packet_is_never_reused(tmp_path):
    root, _, _, options = case(tmp_path)
    (root/'backup-request.json').write_bytes(b'old-private')
    with pytest.raises(RuntimeError): backup.capture_backup(**options)
    assert [p.name for p in root.iterdir()] == ['backup-request.json']
    assert (root/'backup-request.json').read_bytes() == b'old-private'


def test_interruption_retains_partial_backup_without_completion_or_replay(tmp_path):
    root, _, _, options = case(tmp_path)
    def fail(phase):
        if phase == 'after_tracking-snapshot.json': raise RuntimeError('simulated interruption')
    with patch.object(backup, '_boundary', side_effect=fail), pytest.raises(RuntimeError):
        backup.capture_backup(**options)
    assert (root/'tracking-snapshot.json').exists()
    assert not (root/'backup-complete.json').exists()
    with pytest.raises(RuntimeError): backup.capture_backup(**options)


def test_changed_input_identity_or_snapshot_prevents_completion(tmp_path):
    root, state, inputs, options = case(tmp_path)
    calls = 0
    def read():
        nonlocal calls
        calls += 1
        value = deepcopy(inputs)
        if calls > 1:
            raw, _ = value['saved-config.json']; value['saved-config.json'] = (raw, (1, 999))
        return value
    options['read_inputs'] = read
    with pytest.raises(RuntimeError): backup.capture_backup(**options)
    assert not (root/'backup-complete.json').exists()


def test_pending_advanced_or_invalid_binding_fails_before_writes(tmp_path):
    root, state, _, options = case(tmp_path)
    options['read_snapshot'] = lambda: (state, 1)
    with pytest.raises(RuntimeError): backup.capture_backup(**options)
    assert not list(root.iterdir())
    options['read_snapshot'] = lambda: ({**state, backup.INTENTS_KEY: {}}, 0)
    with pytest.raises((RuntimeError, ValueError)): backup.capture_backup(**options)
    assert not list(root.iterdir())
    options['validate_current'] = lambda: (_ for _ in ()).throw(RuntimeError('private-secret'))
    with pytest.raises(RuntimeError): backup.capture_backup(**options)
    assert not list(root.iterdir())


def test_selected_complete_backup_can_be_verified_but_never_authorizes_restore(tmp_path):
    root, state, _, options = case(tmp_path)
    backup.capture_backup(**options)
    fingerprint = hashlib.sha256((root/'backup-complete.json').read_bytes()).hexdigest()
    result = backup.inspect_backup(directory=root, expected_identity=options['expected_identity'],
                                   expected_fingerprint=fingerprint)
    assert result['status'] == 'preview_update_backup_verified'
    assert result['update_authorized'] is False and result['automatic_restoration'] is False
    assert 'private-secret' not in json.dumps(result)
    (root/'tracking-snapshot.json').write_bytes(b'{"private-secret":"changed"}')
    with pytest.raises(RuntimeError):
        backup.inspect_backup(directory=root, expected_identity=options['expected_identity'],
                              expected_fingerprint=fingerprint)


def test_partial_or_different_selected_receipt_is_not_adopted(tmp_path):
    root, _, _, options = case(tmp_path)
    with pytest.raises(FileNotFoundError):
        backup.inspect_backup(directory=root, expected_identity=options['expected_identity'], expected_fingerprint='a'*64)
    backup.capture_backup(**options)
    with pytest.raises(RuntimeError):
        backup.inspect_backup(directory=root, expected_identity=options['expected_identity'], expected_fingerprint='a'*64)
