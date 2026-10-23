"""Bind observed guest NFS uncertainty to a deny-only disposable copy hold."""
from datetime import datetime
from pathlib import Path

from scripts.sqlite_nfs4_guest_lab import require_guest
from app import sqlite_disposable_maintenance_journal as journal
from app.sqlite_disposable_maintenance_controller import fence_disposable_fixture
from app.sqlite_maintenance_bound_copy import run_maintenance_bound_disposable_copy
from app.sqlite_maintenance_review import review_disposable_maintenance
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS


def prepare_uncertain_copy_hold(lab):
    require_guest()
    lab = Path(lab)
    if (lab/'.disposable_nfs4').read_bytes()!=b'DISPOSABLE ONLY\n':
        raise RuntimeError('Marked independent NFS fixture required')
    root = lab/'data/uncertain-copy'
    root.mkdir()
    (root/'.sqlite_disposable_rehearsal').write_text('DISPOSABLE ONLY\n')
    for stage in ('transient','holding','removal','keep'):
        (root/stage).mkdir()
    source = root/'transient/Synthetic Movie'
    source.mkdir()
    (source/'payload').write_bytes(b'RETAIN NFS FIXTURE\n')
    (source/'payload').chmod(0o666)
    state = {section:{} for section in SECTIONS}
    state['first_seen']['Synthetic Movie']='2024-01-01T00:00:00'
    write_offline_snapshot(state,root/'state.db')
    control = lab/'uncertain-maintenance'
    journal.create_disposable_journal(control,bind_linux_boot=True)
    fence_disposable_fixture(control,expected_revision=0)  # Still a synthetic receipt only.
    journal.advance_disposable_journal(control,expected_revision=2,phase='work_pending')
    journal.record_disposable_client_writeback_uncertainty(control,expected_revision=3)
    return root,control


def require_hold_blocks_copy(root,control):
    require_guest()
    before = {path:path.read_bytes() for base in (root,control)
              for path in base.rglob('*') if path.is_file()}
    def forbidden(*args):
        raise AssertionError('Uncertain NFS hold reached collection')
    try:
        run_maintenance_bound_disposable_copy(root=root,database=root/'state.db',
            journal_root=control,maintenance_revision=3,operation_id='nfs-held-copy',
            media_key='Synthetic Movie',title_folder='Synthetic Movie',jellyfin_type='Movie',
            thresholds={'Waiting':7,'Holding':7,'Removal':7,'Keep':0},fetch=forbidden,
            clock=lambda:datetime(2026,1,1))
    except RuntimeError as error:
        if 'Client writeback uncertain' not in str(error):
            raise
    else:
        raise RuntimeError('Uncertain NFS writeback unexpectedly allowed media work')
    report = review_disposable_maintenance(control)
    if report['resume_authorized'] or report.get('maintenance_copy_attempt_present',False):
        raise RuntimeError('Held copy unexpectedly acquired an attempt or resume permit')
    if before!={path:path.read_bytes() for base in (root,control)
                for path in base.rglob('*') if path.is_file()}:
        raise RuntimeError('Held copy/review changed retained bytes')
