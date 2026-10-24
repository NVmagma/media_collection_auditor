"""One verified candidate SQLite capture for dashboard/API tracking projections.

Explicit rehearsal only: no environment selection, JSON fallback, network,
mutation, live-inventory freshness claim or production activation.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import stat

from app.dashboard_tracking_snapshot import read_experimental_sqlite_dashboard_snapshot
from app.integration_status import _project_tracking_status, _project_tracking_titles
from app.sqlite_scheduled_paths import _canonical, _open_directory


@contextmanager
def _candidate_capture(database):
    """Hold parent/database identities and verify exact captured state at exit."""
    parent_fd = database_fd = None
    try:
        path = Path(_canonical(str(database)))
        parent_fd = _open_directory(str(path.parent))
        parent = os.fstat(parent_fd)
        database_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                              dir_fd=parent_fd)
        original = os.fstat(database_fd)
        if not stat.S_ISREG(original.st_mode) or original.st_nlink != 1:
            raise RuntimeError('Unsafe tracking database')
        def verify_identity():
            current_fd = _open_directory(str(path.parent))
            try:
                current = os.fstat(current_fd)
                if (current.st_dev, current.st_ino) != (parent.st_dev, parent.st_ino):
                    raise RuntimeError('Tracking parent changed')
            finally:
                os.close(current_fd)
            current = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            if (not stat.S_ISREG(current.st_mode) or current.st_nlink != 1
                    or (current.st_dev, current.st_ino) != (original.st_dev, original.st_ino)):
                raise RuntimeError('Tracking database changed')
        verify_identity()
        snapshot = read_experimental_sqlite_dashboard_snapshot(path)
        verify_identity()
        yield snapshot
        snapshot.verify_current()
        verify_identity()
    except (OSError, RuntimeError, ValueError, TypeError):
        raise RuntimeError('Candidate SQLite tracking view unavailable') from None
    finally:
        for descriptor in (database_fd, parent_fd):
            if descriptor is not None:
                os.close(descriptor)


def capture_candidate_dashboard_state(database):
    """Detached dashboard state only; never a network/API response by itself."""
    with _candidate_capture(database) as snapshot:
        state = snapshot.state
    return state


def capture_candidate_tracking_view(database, *, holding_days=7):
    """All fixed-schema API projections share one exact database revision."""
    with _candidate_capture(database) as snapshot:
        reports = {
            'summary': _project_tracking_status(lambda: snapshot),
            'oldest_waiting': _project_tracking_titles(lambda: snapshot, 'oldest-waiting', holding_days=holding_days),
            'leaving_soon': _project_tracking_titles(lambda: snapshot, 'leaving-soon', holding_days=holding_days),
        }
        if any(report['status'] == 'unavailable' for report in reports.values()):
            raise RuntimeError('Tracking projection unavailable')
        for report in reports.values():
            report.update(storage_authority='sqlite_candidate', state_revision=snapshot.revision)
        result = {'schema_version': 1, 'status': 'candidate_tracking_view_verified',
            'storage_authority': 'sqlite_candidate', 'state_revision': snapshot.revision,
            'read_only': True, 'freshness_verified': False, 'production_activation': 'disabled',
            'production_authorized': False, **reports}
    return result
