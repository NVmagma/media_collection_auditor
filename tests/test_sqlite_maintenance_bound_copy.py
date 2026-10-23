"""Actual disposable state + locks; no external fence or mocked directory syscall."""
import os
import sqlite3
import sys

import pytest

from app import sqlite_disposable_maintenance_journal as journal
from app.sqlite_disposable_maintenance_controller import fence_disposable_fixture
from app.sqlite_maintenance_bound_copy import run_maintenance_bound_disposable_copy as run
from app.sqlite_maintenance_review import review_disposable_maintenance
from app.state_store import GuardedSQLiteStateStore
from tests.test_sqlite_collected_isolated_runner import lab, item, transport, NOW, FOLDER, LIMITS


@pytest.fixture
def setup(tmp_path, monkeypatch):
    # On Linux use the actual boot/net identities; on the development Mac these
    # two unavailable kernel readers are simulated explicitly for protocol tests.
    if sys.platform != 'linux':
        monkeypatch.setattr(journal,'_linux_boot_id',lambda:'11111111-1111-4111-8111-111111111111')
        monkeypatch.setattr(journal,'_linux_network_namespace',lambda:'net:[12345]')
    root,database=lab(tmp_path)
    control=tmp_path/'maintenance'
    journal.create_disposable_journal(control,bind_linux_boot=True)
    fence_disposable_fixture(control,expected_revision=0)
    journal.advance_disposable_journal(control,expected_revision=2,phase='work_pending')
    return root,database,control


def invoke(setup,fetch,**extra):
    root,database,control=setup
    return run(root=root,database=database,journal_root=control,maintenance_revision=3,
               operation_id='bound-copy',media_key=FOLDER,title_folder=FOLDER,
               jellyfin_type='Movie',thresholds=LIMITS,fetch=fetch,clock=lambda:NOW,**extra)


def untouched(setup,before):
    root,database,_=setup
    assert database.read_bytes()==before
    assert (root/'transient'/FOLDER/'payload').read_text()=='fixture'
    assert not (root/'holding'/FOLDER).exists()


def test_existing_writeback_hold_blocks_before_collection_and_binding(setup):
    _,database,control=setup
    before=database.read_bytes()
    journal.record_disposable_client_writeback_uncertainty(control,expected_revision=3)
    with pytest.raises(RuntimeError,match='Client writeback uncertain'):
        invoke(setup,lambda *a:pytest.fail('No collection while held'))
    untouched(setup,before)
    assert not review_disposable_maintenance(control).get('maintenance_copy_attempt_present',False)


def test_collection_failure_retains_binding_and_blocks_second_attempt(setup):
    _,database,control=setup
    before=database.read_bytes()
    def fail(*args):
        raise RuntimeError('fixture transport unavailable')
    with pytest.raises(RuntimeError):
        invoke(setup,fail)
    untouched(setup,before)
    assert journal.inspect_disposable_journal(control)['phase']=='work_pending'
    review=review_disposable_maintenance(control)
    assert review['maintenance_copy_attempt_present'] is True
    assert review['resume_authorized'] is False
    with pytest.raises(RuntimeError,match='already attempted'):
        invoke(setup,lambda *a:pytest.fail('Retained attempt cannot retry'))


@pytest.mark.parametrize('drift',['journal_lock','journal_path','media_path','phase','hold','operation_binding','state_database'])
def test_scope_loss_during_collection_blocks_without_move(setup,drift):
    root,database,control=setup
    before=database.read_bytes()
    fetch,calls=transport([[item()]])
    changed=False
    def race(*args,**kwargs):
        nonlocal changed
        result=fetch(*args,**kwargs)
        if not changed:
            changed=True
            if drift=='journal_lock':
                (control/'controller.lock').rename(control/'retained.lock')
                (control/'controller.lock').touch()
            elif drift=='journal_path':
                control.rename(control.with_name('retained-maintenance'))
                control.mkdir()
            elif drift=='state_database':
                database.rename(root/'retained-state.db')
                database.write_bytes(before)
            elif drift=='media_path':
                root.rename(root.with_name('retained-media'))
                root.mkdir()
            else:
                # An uncooperative database writer must not be hidden behind a
                # stale read transaction; only test fixture state is altered.
                with sqlite3.connect(control/'maintenance.db') as db:
                    if drift=='phase':
                        db.execute("INSERT INTO events VALUES (4,'outcomes_verified')")
                    elif drift=='hold':
                        db.execute('CREATE TABLE client_writeback_hold(reason TEXT)')
                    else:
                        db.execute("UPDATE maintenance_copy_binding SET operation_id='other-attempt'")
        return result
    with pytest.raises((RuntimeError,OSError)):
        invoke(setup,race)
    actual=root.with_name('retained-media') if drift=='media_path' else root
    assert (actual/'state.db').read_bytes()==before
    assert (actual/'transient'/FOLDER/'payload').read_text()=='fixture'
    assert not (actual/'holding'/FOLDER).exists()


def test_journal_and_media_locks_span_network_collection(setup):
    from app.sqlite_lock import StateLockBusy
    from app.sqlite_isolated_lifecycle_runner import isolated_runner_lock
    root,_,control=setup
    fetch,calls=transport([[item()]])
    checks=[]
    def compete(*args,**kwargs):
        with pytest.raises(StateLockBusy):
            journal.advance_disposable_journal(control,expected_revision=3,phase='outcomes_verified')
        with pytest.raises(RuntimeError,match="Another isolated SQLite runner is active"):
            with isolated_runner_lock(root):
                pytest.fail('Media lock must remain held')
        checks.append(True)
        return fetch(*args,**kwargs)
    try:
        result=invoke(setup,compete)
    except RuntimeError as exc:
        assert 'Atomic no-replace rename' in str(exc)
    else:
        assert result['maintenance_phase']=='outcomes_verified'
        assert result['release_authorized'] is False
        assert result['external_writer_exclusion_verified'] is False
    assert checks
    assert journal.inspect_disposable_journal(control)['phase']!='released'


def test_portable_unbound_journal_cannot_supply_bound_work_scope(tmp_path):
    root,database=lab(tmp_path)
    control=tmp_path/'portable-control'
    journal.create_disposable_journal(control)
    for revision,phase in enumerate(('fence_requested','fixture_fenced','work_pending')):
        journal.advance_disposable_journal(control,expected_revision=revision,phase=phase)
    before=database.read_bytes()
    with pytest.raises(RuntimeError,match='Linux boot-bound fixture required'):
        invoke((root,database,control),lambda *a:pytest.fail('Unbound fixture cannot collect'))
    assert database.read_bytes()==before


@pytest.mark.skipif(sys.platform!='linux',reason='Actual atomic publication/quarantine required')
@pytest.mark.parametrize('fault',['after_retirement_intent','after_source_quarantine','after_completion_checkpoint'])
def test_completion_crash_never_replays_or_releases_maintenance(setup,fault):
    root,database,control=setup
    fetch,_=transport([[item()]])
    with pytest.raises(RuntimeError) as caught:
        invoke(setup,fetch,completion_fault_at=fault)
    if str(caught.value)=='Atomic no-replace rename unsupported':
        state=GuardedSQLiteStateStore(database).load_with_revision()[0]
        assert 'sqlite_pending_operations' in state
        assert (root/'transient'/FOLDER/'payload').read_text()=='fixture'
        pytest.skip('Filesystem refuses atomic publication; retained intent/source verified')
    assert 'Injected completion crash' in str(caught.value)
    assert journal.inspect_disposable_journal(control)['phase']=='work_pending'
    assert not (control/'release.fixture-receipt').exists()
    state=GuardedSQLiteStateStore(database).load_with_revision()[0]
    if fault=='after_completion_checkpoint':
        assert FOLDER in state['queued'] and 'sqlite_pending_operations' not in state
    else:
        assert FOLDER in state['first_seen'] and 'sqlite_pending_operations' in state
    original=root/'transient'/FOLDER if fault=='after_retirement_intent' else root/'.sqlite_retained_sources'/'bound-copy'
    assert (original/'payload').read_text()=='fixture'
    with pytest.raises(RuntimeError,match='already attempted'):
        invoke(setup,lambda *a:pytest.fail('Never replay a failed bound operation'))
