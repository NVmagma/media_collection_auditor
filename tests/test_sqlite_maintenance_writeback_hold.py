"""A recorded uncertain client outcome never becomes a release or write permit."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from app.sqlite_disposable_maintenance_journal import (
    NEXT, advance_disposable_journal as advance, create_disposable_journal as create,
    inspect_disposable_journal as inspect, record_disposable_client_writeback_uncertainty as hold,
)
from app.sqlite_disposable_maintenance_controller import release_disposable_fixture
from app.sqlite_disposable_maintenance_writer import open_disposable_writer
from app.sqlite_maintenance_review import review_disposable_maintenance


def prepared(tmp_path, phase='prepared'):
    root=tmp_path/'lab'
    create(root)
    revision=0
    current='prepared'
    while current!=phase:
        current=NEXT[current]
        revision+=1
        advance(root,expected_revision=revision-1,phase=current)
    return root,revision


@pytest.mark.parametrize('phase',list(NEXT))
def test_every_active_phase_can_only_latch_not_advance_or_release(tmp_path,phase):
    root,revision=prepared(tmp_path,phase)
    before=inspect(root)
    report=hold(root,expected_revision=revision)
    assert report==inspect(root)
    assert report['phase']==before['phase'] and report['revision']==revision
    assert report['client_writeback_uncertain'] is True
    assert report['production_authorized'] is False
    with pytest.raises(RuntimeError,match='Client writeback uncertain'):
        advance(root,expected_revision=revision,phase=NEXT[phase])
    with pytest.raises(RuntimeError,match='Client writeback uncertain'):
        release_disposable_fixture(root,expected_revision=revision)
    assert not (root/'release.fixture-receipt').exists()
    assert inspect(root)==report


def test_held_writer_descriptor_cannot_write_after_hold(tmp_path):
    root,revision=prepared(tmp_path)
    with open_disposable_writer(root) as writer:
        writer.write(b'before')
        hold(root,expected_revision=revision)
        before=(root/'writer.fixture').read_bytes()
        with pytest.raises(RuntimeError,match='Client writeback uncertain'):
            writer.write(b'after')
        with pytest.raises(RuntimeError,match='Client writeback uncertain'):
            with open_disposable_writer(root):
                pytest.fail('Held fixture must not open a new writer')
        assert (root/'writer.fixture').read_bytes()==before


def test_real_process_death_retains_latch_and_detached_review_cannot_clear(tmp_path):
    root,revision=prepared(tmp_path,'outcomes_verified')
    code='''import os,sys
from app.sqlite_disposable_maintenance_journal import record_disposable_client_writeback_uncertainty as hold
hold(sys.argv[1],expected_revision=int(sys.argv[2]))
os._exit(23)
'''
    result=subprocess.run([sys.executable,'-B','-c',code,str(root),str(revision)],
                          cwd=Path(__file__).parents[1],timeout=15)
    assert result.returncode==23
    before=(root/'maintenance.db').read_bytes()
    review=review_disposable_maintenance(root)
    assert review['client_writeback_uncertain'] is True
    assert 'client_writeback_outcome_uncertain' in review['blockers']
    assert review['resume_authorized'] is False and review['clearance_authorized'] is False
    with pytest.raises(RuntimeError,match='Client writeback uncertain'):
        release_disposable_fixture(root,expected_revision=revision)
    assert (root/'maintenance.db').read_bytes()==before
    assert not (root/'release.fixture-receipt').exists()


@pytest.mark.parametrize('bad_revision',[True,-1,'0',1])
def test_bad_revision_never_creates_latch(tmp_path,bad_revision):
    root,_=prepared(tmp_path)
    before=(root/'maintenance.db').read_bytes()
    with pytest.raises((RuntimeError,ValueError)):
        hold(root,expected_revision=bad_revision)
    assert (root/'maintenance.db').read_bytes()==before
    assert 'client_writeback_uncertain' not in inspect(root)


def test_completed_fixture_rejects_late_hold_without_mutation(tmp_path):
    root,revision=prepared(tmp_path,'released')
    before=(root/'maintenance.db').read_bytes()
    with pytest.raises(RuntimeError,match='Released fixture'):
        hold(root,expected_revision=revision)
    assert (root/'maintenance.db').read_bytes()==before


@pytest.mark.parametrize('schema',["CREATE TABLE client_writeback_hold (unrelated TEXT)",
    "CREATE VIEW CLIENT_WRITEBACK_HOLD AS SELECT 1 AS ignored"])
def test_empty_or_unrecognized_latch_object_still_blocks(tmp_path,schema):
    root,revision=prepared(tmp_path)
    with sqlite3.connect(root/'maintenance.db') as db:
        db.execute(schema)
    before=(root/'maintenance.db').read_bytes()
    with pytest.raises(RuntimeError,match='Client writeback uncertain'):
        advance(root,expected_revision=revision,phase='fence_requested')
    assert inspect(root)['client_writeback_uncertain'] is True
    assert (root/'maintenance.db').read_bytes()==before
