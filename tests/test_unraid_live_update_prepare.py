"""Offline live upgrades preserve logical state and at-most-once daily claims."""
import hashlib
import json
import os
from pathlib import Path

import pytest
from app import sqlite_live_binding as live, sqlite_release_profile as build
from app.state_store import GuardedSQLiteStateStore
from scripts import unraid_live_prepare as prepare
from scripts import unraid_live_update_backup as backup
from test_sqlite_live_binding import prepared


def identity(path):
    info = path.stat(); return info.st_dev, info.st_ino


@pytest.fixture
def update_case(prepared, tmp_path, monkeypatch):
    _, source, control, config, settings = prepared
    live.create_live_binding(settings=settings)
    store = GuardedSQLiteStateStore(control/'state.db')
    state, revision = store.load_with_revision()
    state['latest-extension'] = {'clock': '2026-10-30T02:00:00', 'secret': 'fixture-private'}
    store.save_if_revision(state, revision)
    slots = control/'.sqlite_scheduled_slots'; slots.mkdir(mode=0o700)
    # Include both an actual current-date claim and an interrupted claim.
    from datetime import datetime, timezone
    from app.sqlite_scheduled_settings import scheduled_worker_from_settings
    from app.sqlite_scheduled_slot import _manual_slot_identity
    _, _, key = _manual_slot_identity(scheduled_worker_from_settings(settings).schedule,
                                     datetime(2026, 10, 30, 12, tzinfo=timezone.utc))
    for name, raw in [(key, b'{"phase":"slot_claimed"}'), ('e'*64+'.json', b'')]:
        path = slots/name; path.write_bytes(raw); path.chmod(0o600)
    packet = tmp_path/'backup'; packet.mkdir(mode=0o700)
    backup.capture_current(directory=packet, expected_identity=identity(packet),
        container={'Name': '/media_collection_auditor', 'Id': 'a'*64, 'Image': 'sha256:'+'b'*64,
                   'Config': {'Env': [key+'='+value for key, value in settings.items()]}},
        templates=[('my-auditor.xml', b'<Container><Name>media_collection_auditor</Name></Container>')])
    fingerprint = hashlib.sha256((packet/'backup-complete.json').read_bytes()).hexdigest()
    old = {path: path.read_bytes() for path in (source, config, control/'state.db', *slots.iterdir(), *packet.iterdir())}
    logs = tmp_path/'logs'; logs.mkdir(mode=0o700)
    new_control = tmp_path/'control'; new_control.mkdir(mode=0o700)
    monkeypatch.setattr(build, 'SOURCE_REVISION', 'c'*40)
    image = {'Id': 'sha256:'+'c'*64, 'Config': {'Entrypoint': ['python', '-m', 'app.main'],
        'Cmd': None, 'StopSignal': 'SIGINT', 'Volumes': None, 'Labels': {
        'org.opencontainers.image.revision': 'c'*40,
        'io.media-collection-auditor.sqlite-activation': 'scheduled-moves'}}}
    args = dict(backup=packet, backup_identity=identity(packet), backup_fingerprint=fingerprint,
        logs=logs, logs_identity=identity(logs), control=new_control,
        control_identity=identity(new_control), candidate_image=image, _live_update=True)
    return args, state, old, backup.read_daily_claims(control)[0], key


def run(case):
    return prepare.prepare_live_candidate(**case[0])


def test_new_live_binding_keeps_latest_clocks_settings_extensions_and_budget(update_case):
    args, state, old, claims, key = update_case
    report = run(update_case)
    assert report['status'] == 'live_update_binding_prepared_not_started'
    assert report['source_snapshot_revision'] == 1 and report['snapshot_revision'] == 0
    assert report['daily_claims_preserved'] and report['daily_claim_count'] == 2
    assert report['changed_setting_keys'] == []
    assert report['settings_preserved'] and report['update_authorized'] is False
    assert 'fixture-private' not in json.dumps(report)
    assert GuardedSQLiteStateStore(args['control']/'release/state.db').load_with_revision() == (state, 0)
    assert backup.read_daily_claims(args['control']/'release')[0] == claims
    assert all(path.read_bytes() == raw for path, raw in old.items())
    values = dict(line.split('=', 1) for line in (args['logs']/'runtime.env').read_text().splitlines())
    assert live.validate_live_binding(settings=values, for_execution=True)
    from app.sqlite_scheduled_production import _daily_claim_exists
    from datetime import datetime, timezone
    assert _daily_claim_exists(values, datetime(2026, 10, 30, 12, tzinfo=timezone.utc))


@pytest.mark.parametrize('phase', ['after_request', 'before_binding', 'after_daily_claims', 'after_binding', 'before_completion'])
def test_interruption_never_completes_or_replays(update_case, monkeypatch, phase):
    def fail(where):
        if where == phase: raise RuntimeError('fixture interrupted')
    monkeypatch.setattr(prepare, '_boundary', fail)
    with pytest.raises(RuntimeError): run(update_case)
    args, _, old, _, _ = update_case
    assert not (args['logs']/prepare.COMPLETE).exists()
    monkeypatch.setattr(prepare, '_boundary', lambda where: None)
    with pytest.raises(RuntimeError): run(update_case)
    assert all(path.read_bytes() == raw for path, raw in old.items())


@pytest.mark.parametrize('kind', ['claim_removed', 'claim_changed', 'settings', 'backup'])
def test_final_mismatch_never_reports_complete(update_case, monkeypatch, kind):
    args, _, _, _, key = update_case
    def change(where):
        if where != 'before_completion': return
        if kind == 'claim_removed': (args['control']/'release/.sqlite_scheduled_slots'/key).unlink()
        elif kind == 'claim_changed': (args['control']/'release/.sqlite_scheduled_slots'/key).write_bytes(b'changed')
        elif kind == 'settings':
            path = args['logs']/'auditor_config.json'; path.write_bytes(path.read_bytes() + b' ')
        else: (args['backup']/'daily-claims.json').write_bytes(b'{}')
    monkeypatch.setattr(prepare, '_boundary', change)
    with pytest.raises((RuntimeError, ValueError)): run(update_case)
    assert not (args['logs']/prepare.COMPLETE).exists()


def test_wrong_packet_fingerprint_refused_before_any_candidate_write(update_case):
    args = dict(update_case[0]); args['backup_fingerprint'] = 'f'*64
    with pytest.raises(RuntimeError): prepare.prepare_live_candidate(**args)
    assert not list(args['logs'].iterdir()) and not list(args['control'].iterdir())



def test_actual_sigkill_after_claim_copy_never_publishes_live_binding(update_case):
    import signal
    args, _, old, claims, _ = update_case
    child = os.fork()
    if child == 0:
        def die(where):
            if where == 'after_daily_claims': os.kill(os.getpid(), signal.SIGKILL)
        prepare._boundary = die
        try:
            run(update_case)
        finally:
            os._exit(3)
    _, status = os.waitpid(child, 0)
    assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL
    assert not (args['control']/'release'/live.BINDING).exists()
    assert not (args['logs']/prepare.COMPLETE).exists()
    assert backup.read_daily_claims(args['control']/'release')[0] == claims
    assert all(path.read_bytes() == raw for path, raw in old.items())
    with pytest.raises(RuntimeError): run(update_case)


def test_explicit_library_slot_upgrade_preserves_state_and_claims(update_case):
    args, state, old, claims, key = update_case
    report = prepare.prepare_live_candidate(**args, _library_slots=True)
    assert report['initial_maximum_actions'] == 2
    assert report['per_library_action_limit'] == 1
    assert report['changed_setting_keys'] == ['MAX_ACTIONS_PER_RUN']
    assert report['settings_preserved'] is False
    values = dict(line.split('=',1) for line in (args['logs']/'runtime.env').read_text().splitlines())
    assert values['MAX_ACTIONS_PER_RUN'] == '2'
    assert GuardedSQLiteStateStore(args['control']/'release'/'state.db').load_with_revision() == (state,0)
    assert backup.read_daily_claims(args['control']/'release')[0] == claims
    for path, raw in old.items(): assert path.read_bytes() == raw
    live.validate_live_binding(settings=values, for_execution=True)
