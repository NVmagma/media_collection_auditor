"""Candidate production scheduled worker, sealed by the release activation gate.

No automatic database initialization/migration, deletion or service controls.
Marked labs test the same locked run body independently of production selection.
"""
from contextlib import ExitStack, contextmanager
from datetime import datetime
import os
from pathlib import Path
import stat
from time import monotonic

from app.sqlite_backend_gate import require_sqlite_production_activation
from app.sqlite_lock import _exclusive_lock, audit_run_lock
from app.sqlite_scheduled_configured_slot import _configured_run_inputs
from app.sqlite_scheduled_paths import _canonical, _open_directory
from app.sqlite_scheduled_routed_slot import _run_routed_slot_locked
from app.sqlite_scheduled_slot import _claim_scheduled_slot_locked
from app.sqlite_scheduled_worker_cycle import ScheduledWorkerCycle


def production_cycle_step(*, cycle, settings, now, clock=datetime.now):
    """Candidate daily selection, rejected before parsing settings or opening paths."""
    require_sqlite_production_activation()
    return _configured_cycle_step(cycle=cycle, settings=settings, now=now, clock=clock)


def _configured_cycle_step(*, cycle, settings, now, clock):
    from app.sqlite_scheduled_settings import scheduled_worker_from_settings
    values = dict(settings)
    config = scheduled_worker_from_settings(values)
    if not isinstance(cycle, ScheduledWorkerCycle):
        raise ValueError('Daily worker cycle required')
    return cycle.step(now=now, local_time=config.schedule.local_time,
        timezone_name=config.schedule.timezone_name,
        run_due=lambda slot, current: _run_bound_production_slot(settings=values,
            scheduled_at=slot, now=current, clock=clock))


def _run_bound_production_slot(*, settings, scheduled_at, now, clock, timer=monotonic):
    """Private candidate implementation; the public entry above remains sealed."""
    config, scan, protect = _configured_run_inputs(settings=settings, clock=clock)
    source = Path(_canonical(settings.get('STATE_FILE', '/app/logs/auditor_state.json')))
    database = Path(_canonical(settings.get('SQLITE_STATE_FILE', '/app/logs/sqlite_worker/state.db')))
    control = database.parent
    if database.name != 'state.db' or source == database:
        raise ValueError('Dedicated existing control/state.db and distinct JSON source required')
    for library in config.libraries:
        for _, path in library.roots:
            media = Path(path)
            if media == control or media in control.parents or control in media.parents:
                raise ValueError('Control directory and media roots must be disjoint')
    started = timer()
    with audit_run_lock(source) as verify_json:
        with _hold_control_database(control, database) as verify_control:
            def verify_binding():
                verify_json(); verify_control()
            with _claim_scheduled_slot_locked(root=control, schedule=config.schedule,
                    scheduled_at=scheduled_at, now=now, verify_binding=verify_binding) as verify_claim:
                result = _run_routed_slot_locked(database=database, config=config,
                    scheduled_at=scheduled_at, fetch_signals=scan, fetch_protection=protect,
                    arr_sync_requests=None, clock=clock, timer=timer, maximum_titles=100000,
                    maximum_run_seconds=3600, maximum_protection_seconds=30,
                    verify_claim=verify_claim, started_tick=started)
                # The common body reports fixture-only until release validation.
                # Do not relabel its evidence as production authorization.
                return result


@contextmanager
def _hold_control_database(control, database):
    """Bind an existing no-follow control directory/database and persistent lock.

    Never creates state or the control directory. Cooperating runs/migrations
    share the JSON lock above. It does not exclude external media writers.
    """
    with ExitStack() as stack:
        directory_fd = _open_directory(str(control)); stack.callback(os.close, directory_fd)
        directory = os.fstat(directory_fd)
        database_fd = os.open(database.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                              dir_fd=directory_fd)
        stack.callback(os.close, database_fd)
        initial = os.fstat(database_fd)
        if not stat.S_ISREG(initial.st_mode) or initial.st_nlink != 1:
            raise RuntimeError('Existing regular SQLite database required')
        verify_lock = stack.enter_context(_exclusive_lock(control / '.sqlite_runner.lock',
                                                         'Another scheduled worker is active'))
        def verify():
            verify_lock()
            current_fd = _open_directory(str(control))
            try:
                current = os.fstat(current_fd)
                if (current.st_dev, current.st_ino) != (directory.st_dev, directory.st_ino):
                    raise RuntimeError('Control directory replaced')
            finally:
                os.close(current_fd)
            current = os.stat(database.name, dir_fd=directory_fd, follow_symlinks=False)
            if (not stat.S_ISREG(current.st_mode) or current.st_nlink != 1
                    or (current.st_dev, current.st_ino) != (initial.st_dev, initial.st_ino)):
                raise RuntimeError('Control database replaced')
        verify()
        yield verify
        verify()
