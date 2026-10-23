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
from app.state_store import GuardedSQLiteStateStore
from app.sqlite_operation_coordinator import INTENTS_KEY


def run_copy_case(fixture, observer, *, lose_boundary=None, loss_at="collection"):
    if loss_at not in ("collection", "publication", "quarantine", "completion"):
        raise ValueError("Known synthetic boundary required")
    require_guest()
    fixture = Path(fixture)
    if (fixture/'.disposable_writer').read_bytes() != b'DISPOSABLE ONLY\n':
        raise RuntimeError('Marked guest writer required')
    suffix = 'loss-'+loss_at if lose_boundary else 'healthy'
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
        if lose_boundary and loss_at == "collection" and not lost:
            lose_boundary()
            lost = True
        if path == '/Users':
            return [{'Id': 'synthetic-user'}]
        return {'TotalRecordCount': 1, 'Items': [{'Id': 'synthetic-title', 'Type': 'Movie',
            'Path': '/media/'+folder+'/movie.mkv', 'Tags': [],
            'UserData': {'Played': False, 'PlayCount': 0, 'IsFavorite': False}}]}
    def observe():
        nonlocal lost
        reached = False
        if lose_boundary and not lost and loss_at != 'collection':
            if loss_at == 'publication':
                reached = (root/'holding'/folder).is_dir()
            elif loss_at == 'quarantine':
                reached = (root/'.sqlite_retained_sources'/'guest-copy').is_dir()
            else:
                current = GuardedSQLiteStateStore(database).load_with_revision()[0]
                reached = folder in current['queued'] and INTENTS_KEY not in current
            if reached:
                lose_boundary()
                lost = True
        observer()
    arguments = dict(journal_root=control,
        maintenance_revision=3, root=root, database=database, operation_id='guest-copy',
        media_key=folder, title_folder=folder, jellyfin_type='Movie',
        thresholds={'Waiting': 7, 'Holding': 7, 'Removal': 7, 'Keep': 0},
        fetch=fetch, clock=lambda: datetime(2026, 1, 1),
        _fixture_boundary_observer=observe)
    try:
        result = run_maintenance_bound_disposable_copy(**arguments)
    except RuntimeError:
        if not lose_boundary or not lost:
            raise
        original = source if loss_at in ('collection','publication') else root/'.sqlite_retained_sources'/'guest-copy'
        if (original/'payload').read_bytes()!=b'SYNTHETIC ONLY\n':
            raise RuntimeError('Boundary-loss fixture failed original retention')
        published = root/'holding'/folder
        if loss_at == 'collection':
            if database.read_bytes()!=before or published.exists():
                raise RuntimeError('Collection-loss fixture changed state or destination')
        elif (published/'payload').read_bytes()!=b'SYNTHETIC ONLY\n':
            raise RuntimeError('Published copy bytes not retained')
        current = GuardedSQLiteStateStore(database).load_with_revision()[0]
        if loss_at == 'completion':
            if folder not in current['queued'] or INTENTS_KEY in current:
                raise RuntimeError('Expected committed media checkpoint not observed')
        elif loss_at != 'collection':
            if folder not in current['first_seen'] or INTENTS_KEY not in current:
                raise RuntimeError('Pending lifecycle evidence not retained')
        report = review_disposable_maintenance(control,media_root=root)
        if (not report['maintenance_copy_attempt_present'] or report['resume_authorized']
                or journal.inspect_disposable_journal(control)['phase']!='work_pending'):
            raise RuntimeError('Boundary-loss fixture evidence missing')
        pending = report['media_comparison']['pending_operation']
        if loss_at == 'completion' and pending!='no_pending_record_not_completion_proof':
            raise RuntimeError('Absent intent incorrectly interpreted')
        require_replay_rejected(arguments)
        return {'boundary_loss_blocked': True, 'loss_at': loss_at,
                'original_bytes_retained': True, 'media_checkpoint_committed': loss_at=='completion',
                'media_outcome_verified': False, 'retry_rejected_without_byte_changes': True,
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


def require_replay_rejected(arguments, *, same_controller=True):
    """Check retained disposable evidence; never adopt or repair an attempt."""
    require_guest()
    root,control = Path(arguments['root']),Path(arguments['journal_root'])
    retained = {p:p.read_bytes() for base in (root,control)
                for p in base.rglob('*') if p.is_file()}
    try:
        run_maintenance_bound_disposable_copy(**arguments)
    except RuntimeError as error:
        if same_controller:
            if 'already attempted' not in str(error):
                raise
        elif not isinstance(error,journal.MaintenanceControllerSessionChanged):
            raise
    else:
        raise RuntimeError('Retained copy attempt unexpectedly replayed')
    if retained!={p:p.read_bytes() for base in (root,control)
                  for p in base.rglob('*') if p.is_file()}:
        raise RuntimeError('Rejected replay changed retained bytes')
    if (control/'release.fixture-receipt').exists():
        raise RuntimeError('Unexpected synthetic release receipt')
