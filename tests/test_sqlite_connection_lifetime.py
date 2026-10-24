"""Connections must close before return, even when cyclic GC cannot reclaim them.

An open SQLite descriptor can leave a hidden unlinked file on FUSE and prevent
fixture cleanup. Hold strong references deliberately: GC is not the close policy.
"""
import sqlite3

import pytest

from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.sqlite_store import SQLiteStateStore
from app.sqlite_tracking_view import capture_candidate_tracking_view


@pytest.fixture
def connections(monkeypatch):
    original = sqlite3.connect
    held = []
    def connect(*args, **kwargs):
        connection = original(*args, **kwargs)
        held.append(connection)
        return connection
    monkeypatch.setattr(sqlite3, 'connect', connect)
    yield held
    for connection in held:
        connection.close()


def assert_closed(connections):
    assert connections
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            connection.execute('SELECT 1')


def test_offline_writer_closes_before_return_and_verification(tmp_path, connections):
    path = tmp_path / 'state.db'
    write_offline_snapshot({section: {} for section in SECTIONS}, path)
    assert_closed(connections)
    assert path.exists()


def test_revision_and_candidate_reads_close_before_file_replacement(tmp_path, connections):
    path = tmp_path / 'state.db'
    write_offline_snapshot({section: {} for section in SECTIONS}, path)
    SQLiteStateStore(path).load_with_revision()
    capture_candidate_tracking_view(path)
    assert_closed(connections)
    path.rename(tmp_path / 'old.db')
    (tmp_path / 'old.db').unlink()
    assert list(tmp_path.iterdir()) == []


def test_failed_revision_read_also_closes(tmp_path, connections):
    path = tmp_path / 'state.db'
    path.write_bytes(b'not sqlite')
    with pytest.raises(RuntimeError, match='revision unavailable'):
        SQLiteStateStore(path)._revision()
    assert_closed(connections)


def test_failed_writer_closes_and_retains_failed_artifact(tmp_path, connections, monkeypatch):
    import app.sqlite_snapshot_writer as module
    monkeypatch.setattr(module, 'SCHEMA_SQL', 'CREATE TABLE retained(id); INVALID SQL;')
    path = tmp_path / 'state.db'
    with pytest.raises(RuntimeError, match='creation failed'):
        write_offline_snapshot({section: {} for section in SECTIONS}, path)
    assert path.exists()
    assert_closed(connections)
