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

from app.sqlite_arr_catalog import configured_arr_queue_resolver
from app.sqlite_backend_gate import require_sqlite_production_activation
from app.sqlite_lock import _exclusive_lock, audit_run_lock
from app.sqlite_scheduled_configured_slot import _configured_run_inputs
from app.sqlite_scheduled_arr_delivery import configured_arr_delivery
from app.sqlite_scheduled_paths import _canonical, _open_directory
from app.sqlite_scheduled_routed_slot import _run_routed_slot_locked
from app.sqlite_scheduled_slot import _claim_scheduled_slot_locked
from app.sqlite_scheduled_worker_cycle import ScheduledWorkerCycle


def production_cycle_step(*, cycle, settings, now, clock=datetime.now, observer=None):
    """Candidate daily selection, rejected before parsing settings or opening paths."""
    values = require_sqlite_production_activation(settings=settings)
    return _configured_cycle_step(cycle=cycle, settings=values, now=now, clock=clock, observer=observer)


def _configured_cycle_step(*, cycle, settings, now, clock, observer=None):
    from app.sqlite_scheduled_settings import scheduled_worker_from_settings
    values = dict(settings)
    if observer is not None:
        from app.sqlite_scheduled_observations import ScheduledRunObservations
        if not isinstance(observer, ScheduledRunObservations):
            raise ValueError('Scheduled process observations required')
    try:
        config = scheduled_worker_from_settings(values)
    except (ValueError, TypeError):
        if observer is not None:
            observer.invalidate_schedule()
        raise
    if not isinstance(cycle, ScheduledWorkerCycle):
        raise ValueError('Daily worker cycle required')
    def due(slot, current):
        if observer is not None:
            observer.observe_cycle(next_run=cycle.next_run, status='attempted')
        def execute():
            return _run_bound_production_slot(settings=values, scheduled_at=slot, now=current, clock=clock)
        return execute() if observer is None else observer.run_attempt(scheduled_at=slot,
            execute=execute, dry_run=values.get('DRY_RUN', 'true').strip().lower() == 'true')
    try:
        result = cycle.step(now=now, local_time=config.schedule.local_time,
            timezone_name=config.schedule.timezone_name, run_due=due)
    except Exception:
        if observer is not None and cycle.next_run is not None:
            observer.observe_cycle(next_run=cycle.next_run, status='blocked')
        raise
    if observer is not None:
        observer.observe_cycle(next_run=result.next_run, status=result.status)
    return result


def _run_bound_production_slot(*, settings, scheduled_at, now, clock, timer=monotonic):
    """Private candidate implementation; the public entry above remains sealed."""
    config, scan, protect = _configured_run_inputs(settings=settings, clock=clock, allow_dry_run=True)
    dry_run = settings.get('DRY_RUN', 'true').strip().lower() == 'true'
    resolve_arr = None if dry_run else configured_arr_queue_resolver(settings=settings, config=config)
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
                if dry_run:
                    from app.sqlite_scheduled_preview import prepare_scheduled_preview
                    return prepare_scheduled_preview(database=database, config=config,
                        fetch_signals=scan, scheduled_at=scheduled_at, clock=clock,
                        timer=timer, verify_binding=verify_claim, started_tick=started)
                result = _run_routed_slot_locked(database=database, config=config,
                    scheduled_at=scheduled_at, fetch_signals=scan, fetch_protection=protect,
                    arr_sync_requests=None, clock=clock, timer=timer, maximum_titles=100000,
                    maximum_run_seconds=3600, maximum_protection_seconds=30,
                    verify_claim=verify_claim, started_tick=started, resolve_arr_requests=resolve_arr,
                    complete_arr_requests=configured_arr_delivery(settings=settings, config=config))
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
