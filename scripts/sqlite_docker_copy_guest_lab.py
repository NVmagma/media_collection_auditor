"""Synthetic media integration helper called only by the independent guest lab.

No production caller, external-fence claim or real Jellyfin/Arr collection.
"""
from datetime import datetime
from pathlib import Path

from scripts.sqlite_nfs4_guest_lab import require_guest
from app import sqlite_disposable_maintenance_journal as journal
from app.sqlite_disposable_maintenance_controller import fence_disposable_fixture
from app.sqlite_maintenance_bound_copy import run_maintenance_bound_disposable_copy
from app.sqlite_maintenance_review import review_disposable_maintenance
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS


def run_copy_case(fixture, observer, *, lose_boundary=None):
    require_guest()
    fixture = Path(fixture)
    if (fixture/'.disposable_writer').read_bytes() != b'DISPOSABLE ONLY\n':
        raise RuntimeError('Marked guest writer required')
    suffix = 'loss' if lose_boundary else 'healthy'
    # This source is beneath the SAME guest bind exposed to the selected writer.
    root = fixture/'media'/('copy-'+suffix)
    root.mkdir()
    (root/'.sqlite_disposable_rehearsal').write_text('DISPOSABLE ONLY\n')
    folder = 'Synthetic Movie'
    for stage in ('transient', 'holding', 'removal', 'keep'):
        (root/stage).mkdir()
    source = root/'transient'/folder
    source.mkdir()
    (source/'payload').write_bytes(b'SYNTHETIC ONLY\n')
    state = {section: {} for section in SECTIONS}
    state['first_seen'][folder] = '2024-01-01T00:00:00'
    database = root/'state.db'
    write_offline_snapshot(state, database)
    control = fixture/('copy-maintenance-'+suffix)
    journal.create_disposable_journal(control, bind_linux_boot=True)
    fence_disposable_fixture(control, expected_revision=0)  # Synthetic receipt, never an external fence.
    journal.advance_disposable_journal(control, expected_revision=2, phase='work_pending')
    before = database.read_bytes()
    lost = False
    def fetch(path, params):
        nonlocal lost
        if lose_boundary and not lost:
            lose_boundary()
            lost = True
        if path == '/Users':
            return [{'Id': 'synthetic-user'}]
        return {'TotalRecordCount': 1, 'Items': [{'Id': 'synthetic-title', 'Type': 'Movie',
            'Path': '/media/'+folder+'/movie.mkv', 'Tags': [],
            'UserData': {'Played': False, 'PlayCount': 0, 'IsFavorite': False}}]}
    try:
        result = run_maintenance_bound_disposable_copy(journal_root=control,
            maintenance_revision=3, root=root, database=database, operation_id='guest-copy',
            media_key=folder, title_folder=folder, jellyfin_type='Movie',
            thresholds={'Waiting': 7, 'Holding': 7, 'Removal': 7, 'Keep': 0},
            fetch=fetch, clock=lambda: datetime(2026, 1, 1),
            _fixture_boundary_observer=observer)
    except RuntimeError:
        if not lose_boundary or not lost:
            raise
        if (database.read_bytes()!=before or (source/'payload').read_bytes()!=b'SYNTHETIC ONLY\n'
                or (root/'holding'/folder).exists()):
            raise RuntimeError('Boundary-loss fixture failed original/state retention')
        report = review_disposable_maintenance(control)
        if (not report['maintenance_copy_attempt_present'] or report['resume_authorized']
                or journal.inspect_disposable_journal(control)['phase']!='work_pending'):
            raise RuntimeError('Boundary-loss fixture evidence missing')
        return {'boundary_loss_blocked': True, 'original_and_state_retained': True,
                'attempt_retained': True, 'automatic_release': False}
    if lose_boundary:
        raise RuntimeError('Lost selected-writer boundary unexpectedly completed')
    if (result.get('maintenance_phase')!='outcomes_verified'
            or result.get('original_bytes_retained') is not True
            or result.get('external_writer_exclusion_verified') is not False
            or result.get('release_authorized') is not False):
        raise RuntimeError('Guest media integration outcome invalid')
    return {'copy_completed_with_selected_writer_observations': True,
            'original_bytes_retained': True, 'automatic_release': False}
