"""One-shot integration of two disposable protocols; never a production permit.

A boot/network/controller-bound maintenance journal remains locked throughout
one live copy completion. Its binding is retained on every outcome. Synthetic
maintenance checkpoints do not establish external-writer exclusion.
"""
from datetime import datetime
from pathlib import Path
import re
import stat
from time import monotonic

from app import sqlite_disposable_maintenance_journal as journal
from app.sqlite_collected_isolated_runner import _run_collected_isolated_operation
from app.sqlite_isolated_lifecycle_runner import isolated_runner_lock


def _media_identity(root, database):
    directory, state = root.lstat(), database.lstat()
    if (not stat.S_ISDIR(directory.st_mode) or not stat.S_ISREG(state.st_mode)
            or state.st_nlink != 1):
        raise RuntimeError('Unsafe maintenance media binding')
    return (str(root), directory.st_dev, directory.st_ino, state.st_dev, state.st_ino)


def run_maintenance_bound_disposable_copy(*, journal_root, maintenance_revision,
        root, database, operation_id, media_key, title_folder, jellyfin_type,
        thresholds, fetch, clock=datetime.now, timer=monotonic,
        favorites_trigger_keep=True, maximum_age_seconds=60,
        arr_sync_request=None, completion_fault_at=None, _fixture_boundary_observer=None):
    """Persist one attempt before work; never release writers or retry an attempt."""
    if _fixture_boundary_observer is not None and not callable(_fixture_boundary_observer):
        raise ValueError("Callable disposable boundary observer required")
    root, database = Path(root), Path(database)
    journal_root = journal._root(journal_root)
    if (not root.is_absolute() or root.resolve() != root or database != root/'state.db'
            or root == journal_root or root in journal_root.parents or journal_root in root.parents):
        raise ValueError('Distinct unaliased media and control roots required')
    if type(maintenance_revision) is not int or maintenance_revision < 0:
        raise ValueError('Nonnegative integer maintenance revision required')
    if (not isinstance(operation_id, str) or operation_id in ('.', '..')
            or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', operation_id)):
        raise ValueError('Safe disposable operation identity required')
    with journal._database(journal_root, with_verifier=True) as (db, verify_journal):
        def check_scope():
            verify_journal()
            journal._verify_binding(db, journal_root, require_linux_boot=True,
                                    require_controller_session=True)
            journal._require_no_client_writeback_hold(db)
            if journal._history(db)[-1] != (maintenance_revision, 'work_pending'):
                raise RuntimeError('Maintenance work scope changed or unavailable')
        check_scope()
        if db.execute("SELECT 1 FROM sqlite_master WHERE lower(name)=? LIMIT 1",
                      ('maintenance_copy_binding',)).fetchone():
            raise RuntimeError('Maintenance copy already attempted; review required')
        with isolated_runner_lock(root) as verify_media:
            expected = _media_identity(root, database)
            binding_persisted = False
            def verify():
                verify_media()
                check_scope()
                if _fixture_boundary_observer is not None:
                    # Extra deny-only observation, never an ownership credential.
                    if _fixture_boundary_observer() is not None:
                        raise RuntimeError("Boundary observer must return no authority")
                if _media_identity(root, database) != expected:
                    raise RuntimeError('Maintenance media binding changed')
                if binding_persisted:
                    kinds = db.execute("SELECT type FROM sqlite_master WHERE lower(name)=?",
                                       ('maintenance_copy_binding',)).fetchall()
                    if kinds != [('table',)]:
                        raise RuntimeError('Maintenance operation binding unavailable')
                    rows = db.execute('SELECT root, root_device, root_inode, database_device, '
                                      'database_inode, operation_id FROM maintenance_copy_binding LIMIT 2').fetchall()
                    if rows != [(*expected, operation_id)]:
                        raise RuntimeError('Maintenance operation binding changed')
            verify()
            db.execute('CREATE TABLE maintenance_copy_binding '
                       '(root TEXT, root_device INTEGER, root_inode INTEGER, '
                       'database_device INTEGER, database_inode INTEGER, operation_id TEXT)')
            db.execute('INSERT INTO maintenance_copy_binding VALUES (?, ?, ?, ?, ?, ?)',
                       (*expected, operation_id))
            db.commit()  # durable one-shot intent before collection or media work
            binding_persisted = True
            # Release the SQLite write transaction, but retain controller+media
            # locks. Each boundary now observes a fresh journal read, not a stale
            # long-running SQLite snapshot.
            verify()
            result = _run_collected_isolated_operation(root=root, database=database,
                operation_id=operation_id, media_key=media_key, title_folder=title_folder,
                jellyfin_type=jellyfin_type, thresholds=thresholds, fetch=fetch,
                clock=clock, timer=timer, favorites_trigger_keep=favorites_trigger_keep,
                maximum_age_seconds=maximum_age_seconds, arr_sync_request=arr_sync_request,
                completion_fault_at=completion_fault_at, _copy_stage=True, _complete_copy=True,
                _held_runner_binding=verify)
            verify()
            if (result.get('lifecycle_committed') is not True or result.get('intent_cleared') is not True
                    or result.get('original_bytes_retained') is not True):
                raise RuntimeError('Maintenance copy outcome unverified; review required')
            db.execute('BEGIN IMMEDIATE')
            verify()
            report = journal._append(db, expected_revision=maintenance_revision,
                                     phase='outcomes_verified')
            return {**result, 'maintenance_phase':report['phase'], 'fixture_only':True,
                    'automatic_action':'none', 'release_authorized':False,
                    'external_writer_exclusion_verified':False, 'production_authorized':False}
