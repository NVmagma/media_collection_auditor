"""Marker reads stay bounded and reject real stat/open substitutions."""
import multiprocessing
import os
from pathlib import Path

import pytest


def _marker_race(root, kind, connection):
    from app.sqlite_isolated_lifecycle_runner import isolated_runner_lock
    import app.sqlite_disposable_maintenance_journal as journal
    root = Path(root)
    name = '.sqlite_disposable_rehearsal' if kind == 'runner' else '.disposable_maintenance'
    marker = root / name
    content = b'DISPOSABLE ONLY\n' if kind == 'runner' else journal.MARKER
    marker.write_bytes(content)
    database = root / ('state.db' if kind == 'runner' else 'maintenance.db')
    database.write_bytes(b'fixture bytes must remain unchanged')
    original = root / 'retained-marker'
    changed = False
    is_file, lstat = Path.is_file, Path.lstat

    def replace():
        nonlocal changed
        if not changed:
            changed = True
            marker.rename(original)
            os.mkfifo(marker)

    def raced_is_file(path):
        result = is_file(path)
        if kind == 'runner' and path == marker:
            replace()
        return result

    def raced_lstat(path, *args, **kwargs):
        result = lstat(path, *args, **kwargs)
        if kind == 'maintenance' and path == marker:
            replace()
        return result

    Path.is_file, Path.lstat = raced_is_file, raced_lstat
    try:
        try:
            if kind == 'runner':
                with isolated_runner_lock(root):
                    connection.send({'rejected': False})
                    return
            else:
                journal._fixture(root)
        except RuntimeError:
            connection.send({'rejected': True, 'changed': changed,
                             'original_retained': original.read_bytes() == content,
                             'database_unchanged': database.read_bytes() == b'fixture bytes must remain unchanged',
                             'no_lock_created': not (root / '.sqlite_runner.lock').exists() and not (root / 'controller.lock').exists()})
        else:
            connection.send({'rejected': False})
    finally:
        Path.is_file, Path.lstat = is_file, lstat
        connection.close()


@pytest.mark.parametrize('kind', ['runner', 'maintenance'])
def test_marker_substituted_by_fifo_cannot_hang_or_enter_operation(tmp_path, kind):
    context = multiprocessing.get_context('spawn')
    receiver, sender = context.Pipe(duplex=False)
    child = context.Process(target=_marker_race, args=(str(tmp_path), kind, sender))
    child.start()
    sender.close()
    try:
        child.join(8)
        assert not child.is_alive(), 'Marker validation blocked on a FIFO'
        assert child.exitcode == 0
        assert receiver.poll()
        report = receiver.recv()
        assert set(report) == {'rejected', 'changed', 'original_retained', 'database_unchanged', 'no_lock_created'}
        assert all(value is True for value in report.values())
    finally:
        if child.is_alive():
            child.terminate()
            child.join(5)
        receiver.close()


@pytest.mark.parametrize('kind', ['runner', 'maintenance'])
def test_oversized_marker_uses_bounded_descriptor_read(tmp_path, monkeypatch, kind):
    from app.sqlite_isolated_lifecycle_runner import isolated_runner_lock
    import app.sqlite_disposable_maintenance_journal as journal
    name = '.sqlite_disposable_rehearsal' if kind == 'runner' else '.disposable_maintenance'
    marker = tmp_path / name
    content = b'DISPOSABLE ONLY\n' if kind == 'runner' else journal.MARKER
    marker.write_bytes(content + b'x' * 100000)
    (tmp_path / 'state.db').write_bytes(b'fixture')
    original = os.pread
    sizes = []
    def bounded(fd, size, offset):
        sizes.append(size)
        assert size <= len(content) + 1
        return original(fd, size, offset)
    monkeypatch.setattr(os, 'pread', bounded)
    monkeypatch.setattr(Path, 'read_text', lambda *a, **k: pytest.fail('No pathname text read'))
    monkeypatch.setattr(Path, 'read_bytes', lambda *a, **k: pytest.fail('No pathname byte read'))
    with pytest.raises(RuntimeError, match='marker'):
        if kind == 'runner':
            with isolated_runner_lock(tmp_path):
                pytest.fail('Invalid marker admitted')
        else:
            journal._fixture(tmp_path)
    assert sizes == [len(content) + 1]
