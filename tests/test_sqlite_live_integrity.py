from contextlib import closing
from copy import deepcopy
import sqlite3
import pytest
from app.sqlite_live_integrity import KEY,initialize
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import read_snapshot
from app.state_store import GuardedSQLiteStateStore


@pytest.fixture
def live_database(tmp_path):
    path=tmp_path/'state.db'
    state={key:{} for key in ('first_seen','queued','in_removal','keep_seen','arr_sync_pending')}
    state['custom']={'private':'retained'}
    write_offline_snapshot(state,path)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute('BEGIN IMMEDIATE');initialize(connection,state=state,revision=0);connection.commit()
    return path,state


def test_guarded_revisions_advance_integrity_without_freezing_initial_snapshot(live_database):
    path,state=live_database;store=GuardedSQLiteStateStore(path)
    for revision in range(3):
        current,observed=store.load_with_revision();assert observed==revision
        current['queued']['fixture-title']='2026-01-01T00:00:00'
        current['custom']['counter']=revision
        store.save_if_revision(current,revision)
        assert read_snapshot(path)==current
    assert store.load_with_revision()[1]==3
    assert state['custom']=={'private':'retained'}


@pytest.mark.parametrize('mutation',[
    "UPDATE extra_state SET value_json='{}' WHERE key='custom'",
    "INSERT INTO metadata(key,value) VALUES ('state_revision','1') ON CONFLICT(key) DO UPDATE SET value=excluded.value",
    "UPDATE metadata SET value='{}' WHERE key='live_state_integrity_v1'",
])
def test_raw_mutation_is_not_adopted_by_reads_or_guarded_writes(live_database,mutation):
    path,state=live_database
    with closing(sqlite3.connect(path)) as connection:connection.execute(mutation);connection.commit()
    before=path.read_bytes()
    with pytest.raises(RuntimeError):read_snapshot(path)
    with pytest.raises(RuntimeError):GuardedSQLiteStateStore(path).save_if_revision(state,0)
    assert path.read_bytes()==before


def test_failed_transaction_rolls_back_state_revision_and_integrity_together(live_database):
    path,state=live_database
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TRIGGER refuse_integrity BEFORE UPDATE ON metadata WHEN OLD.key='live_state_integrity_v1' BEGIN SELECT RAISE(ABORT,'fixture'); END")
        connection.commit()
    changed=deepcopy(state);changed['custom']['new']='not committed'
    with pytest.raises(RuntimeError):GuardedSQLiteStateStore(path).save_if_revision(changed,0)
    assert GuardedSQLiteStateStore(path).load_with_revision()==(state,0)


def test_legacy_database_remains_unmodified_until_explicit_opt_in(tmp_path):
    path=tmp_path/'legacy.db';state={key:{} for key in ('first_seen','queued','in_removal','keep_seen','arr_sync_pending')}
    write_offline_snapshot(state,path)
    GuardedSQLiteStateStore(path).save_if_revision(state,0)
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute('SELECT value FROM metadata WHERE key=?',(KEY,)).fetchone() is None
        with pytest.raises(RuntimeError):initialize(connection,state=state,revision=1)


def test_initialization_never_replaces_an_existing_integrity_record(live_database):
    path,state=live_database
    with closing(sqlite3.connect(path)) as connection:
        connection.execute('BEGIN IMMEDIATE')
        with pytest.raises(sqlite3.IntegrityError):initialize(connection,state=state,revision=0)
        connection.rollback()
    assert read_snapshot(path)==state
