"""Real entry-substitution races run in killable children, never production media."""
import multiprocessing
import os
from pathlib import Path
import stat

import pytest


def _substitute_and_read(root, phase, replacement, nested, connection):
    import app.sqlite_disposable_copy_stage as stage
    from app.sqlite_copy_live_verification import _metadata_snapshot
    root = Path(root)
    source = root / 'source'
    destination = root / 'destination'
    source.mkdir()
    destination.mkdir()
    parent = source / 'Extras' if nested else source
    parent.mkdir(exist_ok=True)
    target = parent / 'payload'
    target.write_bytes(b'original fixture bytes')
    saved = parent / 'retained-original'
    source_fd = os.open(source, stage.FLAGS)
    destination_fd = os.open(destination, stage.FLAGS)
    real_open = os.open
    changed = False

    def raced_open(name, flags, *args, **kwargs):
        nonlocal changed
        if name == 'payload' and kwargs.get('dir_fd') is not None and not changed:
            changed = True
            target.rename(saved)
            if replacement == 'fifo':
                os.mkfifo(target)
            elif replacement == 'symlink':
                target.symlink_to(saved.name)
            else:
                target.mkdir()
        return real_open(name, flags, *args, **kwargs)

    try:
        stage.os.open = raced_open
        try:
            if phase == 'manifest':
                stage._manifest(source_fd)
            elif phase == 'copy':
                stage._copy_tree(source_fd, destination_fd)
            else:
                _metadata_snapshot(source_fd)
        except (OSError, RuntimeError) as error:
            connection.send({'rejected': True, 'changed': changed,
                             'error': type(error).__name__,
                             'original_retained': saved.read_bytes() == b'original fixture bytes',
                             'destination_payload_absent': not (destination / ('Extras' if nested else '') / 'payload').exists()})
        else:
            connection.send({'rejected': False, 'changed': changed})
    finally:
        stage.os.open = real_open
        os.close(source_fd)
        os.close(destination_fd)
        connection.close()


@pytest.mark.parametrize('phase', ['manifest', 'copy', 'metadata'])
@pytest.mark.parametrize('replacement', ['fifo', 'symlink', 'directory'])
@pytest.mark.parametrize('nested', [False, True])
def test_entry_substitution_rejected_without_waiting_for_fifo_writer(tmp_path, phase, replacement, nested):
    context = multiprocessing.get_context('spawn')
    receiver, sender = context.Pipe(duplex=False)
    child = context.Process(target=_substitute_and_read,
                            args=(str(tmp_path), phase, replacement, nested, sender))
    child.start()
    sender.close()
    try:
        child.join(8)
        assert not child.is_alive(), 'Verification blocked after source entry became a FIFO'
        assert child.exitcode == 0
        assert receiver.poll(), 'Child failed without verifying substitution rejection'
        result = receiver.recv()
        assert result['rejected'] is True
        assert result['changed'] is True
        assert result['original_retained'] is True
        assert result['destination_payload_absent'] is True
        assert result['error'] == ('OSError' if replacement == 'symlink' else 'RuntimeError')
    finally:
        if child.is_alive():
            child.terminate()
            child.join(5)
        receiver.close()


def _intent_race(root, connection):
    import app.sqlite_disposable_copy_stage as stage
    from app.sqlite_snapshot_writer import write_offline_snapshot
    from app.sqlite_state import SECTIONS
    from app.sqlite_operation_coordinator import INTENTS_KEY
    from app.state_store import GuardedSQLiteStateStore
    root = Path(root)
    (root / '.sqlite_disposable_rehearsal').write_text('DISPOSABLE ONLY\n')
    parent = root / 'transient' / 'Movie A'
    parent.mkdir(parents=True)
    payload = parent / 'payload'
    payload.write_bytes(b'original fixture bytes')
    state = {section: {} for section in SECTIONS}
    state['first_seen']['Movie A'] = '2024-01-01T00:00:00'
    database = root / 'state.db'
    write_offline_snapshot(state, database)
    real_open, real_copy = os.open, stage._copy_tree
    armed, changed = False, False

    def arm_copy(*args):
        nonlocal armed
        armed = True
        return real_copy(*args)

    def raced_open(name, flags, *args, **kwargs):
        nonlocal changed
        if armed and name == 'payload' and kwargs.get('dir_fd') is not None and not changed:
            changed = True
            payload.rename(parent / 'retained-original')
            os.mkfifo(payload)
        return real_open(name, flags, *args, **kwargs)

    try:
        stage._copy_tree = arm_copy
        stage.os.open = raced_open
        try:
            stage.stage_disposable_copy_with_intent(root=root, title_folder='Movie A',
                                                   media_key='Movie A', operation_id='fifo-operation')
        except RuntimeError as error:
            current, revision = GuardedSQLiteStateStore(database).load_with_revision()
            connection.send({
                'changed': changed, 'error': str(error),
                'clock_unchanged': current['first_seen'] == state['first_seen'],
                'pending': current[INTENTS_KEY]['id'] == 'fifo-operation',
                'copy_unverified': current[INTENTS_KEY]['details']['copy_phase'] == 'prepared',
                'no_arr_queue': not current['arr_sync_pending'],
                'no_holding_clock': not current['queued'],
                'original_retained': (parent / 'retained-original').read_bytes() == b'original fixture bytes',
                'fifo_retained': stat.S_ISFIFO(payload.lstat().st_mode),
                'no_payload_published': not (root / '.sqlite_copy_staging' / 'fifo-operation' / 'payload').exists(),
            })
        else:
            connection.send({'changed': changed, 'error': None})
    finally:
        stage.os.open, stage._copy_tree = real_open, real_copy
        connection.close()


def test_fifo_race_after_durable_intent_retains_original_clocks_and_pending_operation(tmp_path):
    context = multiprocessing.get_context('spawn')
    receiver, sender = context.Pipe(duplex=False)
    child = context.Process(target=_intent_race, args=(str(tmp_path), sender))
    child.start()
    sender.close()
    try:
        child.join(8)
        assert not child.is_alive(), 'Copy hung after durable intent instead of returning a pending failure'
        assert child.exitcode == 0
        assert receiver.poll()
        report = receiver.recv()
        assert report.pop('error') == 'Source file changed during copy'
        assert all(value is True for value in report.values()), report
    finally:
        if child.is_alive():
            child.terminate()
            child.join(5)
        receiver.close()
