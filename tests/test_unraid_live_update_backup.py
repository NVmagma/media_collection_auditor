"""Live backup observations preserve advanced tracking and every daily claim."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import pytest
from scripts import unraid_live_update_backup as backup
from test_unraid_update_backup import case
from test_sqlite_live_binding import prepared


def options(tmp_path):
    root, state, inputs, values = case(tmp_path)
    values.pop('reviewed_settings_change', None)
    values['read_snapshot'] = lambda: (deepcopy(state), 17)
    control = tmp_path / 'control'; control.mkdir(mode=0o700)
    slots = control / '.sqlite_scheduled_slots'; slots.mkdir(mode=0o700)
    for name, raw in [('a'*64+'.json', b'{"local_date":"2026-10-30"}'),
                      ('b'*64+'.json', b''), ('c'*64+'.json', b'{"partial":')]:
        path = slots / name; path.write_bytes(raw); path.chmod(0o600)
    values['read_claims'] = lambda: backup.read_daily_claims(control)
    return root, state, inputs, values, control


def fingerprint(root):
    return hashlib.sha256((root/'backup-complete.json').read_bytes()).hexdigest()


def test_advanced_tracking_and_partial_claims_are_preserved_exactly(tmp_path):
    root, state, inputs, values, control = options(tmp_path)
    before = backup.read_daily_claims(control)
    result = backup.capture_backup(**values)
    assert result['snapshot_revision'] == 17 and result['daily_claim_count'] == 3
    assert not result['update_authorized'] and not result['backup_freshness_verified']
    assert 'private-secret' not in json.dumps(result)
    assert json.loads((root/'tracking-snapshot.json').read_bytes()) == state
    assert json.loads((root/'daily-claims.json').read_bytes()) == before[0]
    assert backup.read_daily_claims(control) == before
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in root.iterdir())
    checked = backup.inspect_backup(directory=root, expected_identity=values['expected_identity'],
                                    expected_fingerprint=fingerprint(root))
    assert checked['snapshot_revision'] == 17 and checked['daily_claim_count'] == 3
    assert checked['update_authorized'] is False


@pytest.mark.parametrize('change', ['state', 'claims', 'input', 'binding'])
def test_concurrent_change_never_completes(tmp_path, monkeypatch, change):
    root, state, inputs, values, control = options(tmp_path)
    failed = []
    values['validate_current'] = lambda: (_ for _ in ()).throw(RuntimeError('private-secret')) if failed else None
    def mutate(phase):
        if phase != 'before_completion': return
        if change == 'state': state['custom-new'] = True
        elif change == 'claims':
            path = control/'.sqlite_scheduled_slots'/('d'*64+'.json')
            path.write_bytes(b''); path.chmod(0o600)
        elif change == 'input': inputs['saved-config.json'] = (b'{}', (9, 9))
        else: failed.append(True)
    monkeypatch.setattr(backup, '_boundary', mutate)
    with pytest.raises(RuntimeError): backup.capture_backup(**values)
    assert not (root/'backup-complete.json').exists()


def test_interruption_retains_partial_packet_without_replay(tmp_path, monkeypatch):
    root, _, _, values, _ = options(tmp_path)
    def die(phase):
        if phase == 'after_daily-claims.json': raise RuntimeError('interrupted')
    monkeypatch.setattr(backup, '_boundary', die)
    with pytest.raises(RuntimeError): backup.capture_backup(**values)
    assert (root/'daily-claims.json').exists() and not (root/'backup-complete.json').exists()
    monkeypatch.setattr(backup, '_boundary', lambda phase: None)
    with pytest.raises(RuntimeError): backup.capture_backup(**values)


@pytest.mark.parametrize('kind', ['symlink', 'hardlink', 'unexpected', 'permissions'])
def test_unsafe_claim_entries_block_before_packet_writes(tmp_path, kind):
    root, _, _, values, control = options(tmp_path)
    slots = control/'.sqlite_scheduled_slots'
    path = slots/('d'*64+'.json')
    if kind == 'symlink': path.symlink_to(slots/('a'*64+'.json'))
    elif kind == 'hardlink': os.link(slots/('a'*64+'.json'), path)
    elif kind == 'unexpected': (slots/'unknown.json').write_bytes(b'')
    else: (slots/('a'*64+'.json')).chmod(0o644)
    with pytest.raises((RuntimeError, OSError)): backup.capture_backup(**values)
    assert not list(root.iterdir())


def test_pending_operation_never_becomes_migratable_backup(tmp_path):
    root, state, _, values, _ = options(tmp_path)
    state[backup.INTENTS_KEY] = {}
    with pytest.raises((RuntimeError, ValueError)): backup.capture_backup(**values)
    assert not list(root.iterdir())


def test_missing_claim_directory_remains_absent(tmp_path):
    control = tmp_path/'control'; control.mkdir(mode=0o700)
    claims, _ = backup.read_daily_claims(control)
    assert claims == {'present': False, 'entries': {}}
    assert not list(control.iterdir())


@pytest.mark.parametrize('name', backup.FILES)
def test_packet_corruption_refuses_inspection_without_repair(tmp_path, name):
    root, _, _, values, _ = options(tmp_path)
    backup.capture_backup(**values); selected = fingerprint(root)
    (root/name).write_bytes(b'changed-private')
    with pytest.raises((RuntimeError, ValueError)):
        backup.inspect_backup(directory=root, expected_identity=values['expected_identity'],
                              expected_fingerprint=selected)
    assert (root/name).read_bytes() == b'changed-private'


def test_actual_live_validator_captures_advanced_state_without_mutating_inputs(prepared, tmp_path, monkeypatch):
    from app.sqlite_live_binding import create_live_binding
    from app.state_store import GuardedSQLiteStateStore
    _, source, control, config, settings = prepared
    create_live_binding(settings=settings)
    store = GuardedSQLiteStateStore(control/'state.db')
    state, revision = store.load_with_revision()
    state['retained-extension'] = {'clock': '2026-10-30T02:00:00'}
    store.save_if_revision(state, revision)
    slots = control/'.sqlite_scheduled_slots'; slots.mkdir(mode=0o700)
    claim = slots/('f'*64+'.json'); claim.write_bytes(b'partial'); claim.chmod(0o600)
    before = {path: path.read_bytes() for path in (source, config, control/'state.db', claim)}
    root = tmp_path/'actual-packet'; root.mkdir(mode=0o700)
    # Published live images package app/ only, not the checkout's scripts/.
    import builtins
    original_import = builtins.__import__
    def packaged_import(name, *args, **kwargs):
        if name == 'scripts' or name.startswith('scripts.'):
            raise ModuleNotFoundError('scripts are not packaged')
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', packaged_import)
    result = backup.capture_current(directory=root,
        expected_identity=(root.stat().st_dev, root.stat().st_ino),
        container={'Name': '/media_collection_auditor', 'Id': 'a'*64,
                   'Image': 'sha256:'+'b'*64,
                   'Config': {'Env': [key+'='+value for key, value in settings.items()]}},
        templates=[('my-auditor.xml', b'<Container><Name>media_collection_auditor</Name></Container>')])
    assert result['snapshot_revision'] == 1 and result['daily_claim_count'] == 1
    assert all(path.read_bytes() == raw for path, raw in before.items())
    assert json.loads((root/'tracking-snapshot.json').read_bytes()) == state



def test_identical_claim_replacement_never_completes(tmp_path, monkeypatch):
    root, _, _, values, control = options(tmp_path)
    def replace(phase):
        if phase != 'before_completion': return
        path = control/'.sqlite_scheduled_slots'/('a'*64+'.json')
        old = path.read_bytes()
        path.rename(tmp_path/'retained-old-claim')
        path.write_bytes(old); path.chmod(0o600)
    monkeypatch.setattr(backup, '_boundary', replace)
    with pytest.raises(RuntimeError): backup.capture_backup(**values)
    assert not (root/'backup-complete.json').exists()


def test_identical_packet_directory_replacement_is_not_adopted(tmp_path, monkeypatch):
    import shutil
    root, _, _, values, _ = options(tmp_path)
    def replace(phase):
        if phase != 'before_completion': return
        root.rename(tmp_path/'retained-packet')
        shutil.copytree(tmp_path/'retained-packet', root)
    monkeypatch.setattr(backup, '_boundary', replace)
    with pytest.raises(RuntimeError): backup.capture_backup(**values)
    assert not (root/'backup-complete.json').exists()
    assert not (tmp_path/'retained-packet'/'backup-complete.json').exists()


def test_actual_sigkill_retains_incomplete_packet_and_claims(tmp_path):
    import signal
    root, _, _, values, control = options(tmp_path)
    before = backup.read_daily_claims(control)
    child = os.fork()
    if child == 0:
        def die(phase):
            if phase == 'after_daily-claims.json': os.kill(os.getpid(), signal.SIGKILL)
        backup._boundary = die
        try:
            backup.capture_backup(**values)
        finally:
            os._exit(3)
    _, status = os.waitpid(child, 0)
    assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL
    assert (root/'daily-claims.json').exists() and not (root/'backup-complete.json').exists()
    assert backup.read_daily_claims(control) == before
    with pytest.raises(RuntimeError): backup.capture_backup(**values)
