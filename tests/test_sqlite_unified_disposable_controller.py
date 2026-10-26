import pytest
import sqlite3
from app.sqlite_unified_disposable_controller import run_unified_disposable_copy
from tests.test_sqlite_maintenance_bound_copy import setup, untouched
from tests.test_sqlite_collected_isolated_runner import FOLDER, LIMITS, NOW
from app.sqlite_maintenance_review import review_disposable_maintenance


@pytest.mark.parametrize('failed_domain', ['docker','nfs','host_storage'])
def test_one_missing_live_domain_blocks_before_attempt_or_collection(setup, failed_domain):
    root,database,control=setup
    before=database.read_bytes()
    def deny(): raise RuntimeError('private adapter error')
    providers={name:(deny if name==failed_domain else lambda:None)
               for name in ('docker','nfs','host_storage')}
    with pytest.raises(RuntimeError,match=failed_domain):
        run_unified_disposable_copy(**providers, root=root,database=database,journal_root=control,
            maintenance_revision=3,operation_id='unified',media_key=FOLDER,title_folder=FOLDER,
            jellyfin_type='Movie',thresholds=LIMITS,clock=lambda:NOW,
            fetch=lambda *a:pytest.fail('No collection'))
    untouched(setup,before)
    assert review_disposable_maintenance(control)['resume_authorized'] is False
    with sqlite3.connect(control/'maintenance.db') as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='maintenance_copy_binding'").fetchone()


def test_single_observer_override_rejected():
    with pytest.raises(ValueError,match='cannot be overridden'):
        run_unified_disposable_copy(docker=lambda:None,nfs=lambda:None,host_storage=lambda:None,
            _fixture_boundary_observer=lambda:None)


def test_live_storage_drift_blocks_before_attempt(setup, monkeypatch):
    import sys
    from app import sqlite_disposable_storage_backend as storage
    root,database,control=setup
    before=database.read_bytes()
    if sys.platform != 'linux':
        monkeypatch.setattr(storage,'read_fd_mount_id',lambda fd:123)
        monkeypatch.setattr(storage,'read_mount_namespace_identity',lambda:(1,2))
    with storage.held_disposable_storage_observer(root=root) as verify:
        (root/'holding').rename(root/'retained-holding')
        (root/'holding').mkdir()
        with pytest.raises(RuntimeError,match='host_storage'):
            run_unified_disposable_copy(docker=lambda:None,nfs=lambda:None,host_storage=verify,
                root=root,database=database,journal_root=control,maintenance_revision=3,
                operation_id='storage-drift',media_key=FOLDER,title_folder=FOLDER,
                jellyfin_type='Movie',thresholds=LIMITS,clock=lambda:NOW,
                fetch=lambda *a:pytest.fail('No collection'))
    untouched(setup,before)
    with sqlite3.connect(control/'maintenance.db') as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='maintenance_copy_binding'").fetchone()
