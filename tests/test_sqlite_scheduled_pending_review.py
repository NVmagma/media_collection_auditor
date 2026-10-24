from pathlib import Path

from app.sqlite_scheduled_pending_review import review_scheduled_pending
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS


def test_pending_review_preserves_database_and_never_follows_stored_paths(tmp_path, monkeypatch):
    database = tmp_path / 'state.db'
    state = {name: {} for name in SECTIONS}
    state['sqlite_pending_operations'] = {'kind': 'move', 'phase': 'intent_recorded', 'details': {
        'source': '/never/read/this/secret', 'destination': '/never/create/this'}}
    write_offline_snapshot(state, database)
    before = database.read_bytes(); files = set(tmp_path.iterdir())
    original = Path.lstat
    def lstat(path, *args, **kwargs):
        assert not str(path).startswith('/never/')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'lstat', lstat)
    report = review_scheduled_pending(database)
    assert report['status'] == 'operator_review_required'
    assert report['phase'] == 'intent_recorded'
    assert report['replay_allowed'] is False and report['clearance_authorized'] is False
    assert 'secret' not in str(report)
    assert before == database.read_bytes() and set(tmp_path.iterdir()) == files


def test_missing_database_never_initialized(tmp_path):
    path = tmp_path / 'missing.db'
    assert review_scheduled_pending(path)['status'] == 'blocked'
    assert not path.exists()


def test_clean_database_is_not_a_move_or_resume_permit(tmp_path):
    path = tmp_path / 'state.db'; write_offline_snapshot({s: {} for s in SECTIONS}, path)
    report = review_scheduled_pending(path)
    assert report['status'] == 'no_pending_operation_observed'
    assert report['clearance_authorized'] is False


def test_symlink_database_rejected(tmp_path):
    real = tmp_path / 'real.db'; write_offline_snapshot({s: {} for s in SECTIONS}, real)
    alias = tmp_path / 'alias.db'; alias.symlink_to(real)
    assert review_scheduled_pending(alias)['status'] == 'blocked'


def test_wal_snapshot_review_does_not_create_shared_memory_files(tmp_path):
    import sqlite3
    path = tmp_path / 'state.db'; write_offline_snapshot({s: {} for s in SECTIONS}, path)
    with sqlite3.connect(path) as connection:
        assert connection.execute('PRAGMA journal_mode=WAL').fetchone() == ('wal',)
    before = {entry.name: entry.read_bytes() for entry in tmp_path.iterdir()}
    assert review_scheduled_pending(path)['status'] == 'blocked'
    assert {entry.name: entry.read_bytes() for entry in tmp_path.iterdir()} == before
