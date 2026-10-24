"""Read-only pending-operation review. Stored media paths are never followed."""
from pathlib import Path
import stat
import os

from app.sqlite_operation_coordinator import INTENTS_KEY
from app.state_store import GuardedSQLiteStateStore


def review_scheduled_pending(database):
    base = {'read_only': True, 'automatic_action': 'none', 'replay_allowed': False,
            'clearance_authorized': False, 'production_activation': 'disabled',
            'production_authorized': False}
    try:
        database = Path(database)
        before = database.lstat()
        if (not database.is_absolute() or database.resolve() != database
                or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1):
            raise RuntimeError('Unsafe database path')
        # A read-only SQLite connection may need WAL shared-memory sidecars.
        # Refuse WAL/hot-journal review rather than create any recovery artifacts.
        fd = os.open(database, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise RuntimeError('Unsafe database descriptor')
            header = os.pread(fd, 100, 0)
            if len(header) != 100 or header[:16] != b'SQLite format 3\0' or header[18:20] != b'\1\1':
                raise RuntimeError('Offline rollback-journal snapshot required')
        finally:
            os.close(fd)
        if any(os.path.lexists(str(database) + suffix) for suffix in ('-wal', '-shm', '-journal')):
            raise RuntimeError('Active or uncertain SQLite journal')
        state, revision = GuardedSQLiteStateStore(database).load_with_revision()
        after = database.lstat()
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise RuntimeError('Database changed during review')
        if INTENTS_KEY not in state:
            return {**base, 'status': 'no_pending_operation_observed', 'revision': revision}
        pending = state[INTENTS_KEY]
        if (not isinstance(pending, dict) or pending.get('kind') != 'move'
                or pending.get('phase') not in ('intent_recorded', 'applied_pending_reconciliation')
                or not isinstance(pending.get('details'), dict)):
            raise RuntimeError('Unknown pending operation')
        return {**base, 'status': 'operator_review_required', 'revision': revision,
                'phase': pending['phase'], 'reason': 'retained_move_outcome_unverified'}
    except Exception:
        return {**base, 'status': 'blocked', 'reason': 'pending_review_unavailable_or_changed'}
