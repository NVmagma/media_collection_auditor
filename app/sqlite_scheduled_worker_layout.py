"""Deployment-shaped control/media separation, restricted to disposable labs.

No public production activation or marker bypass. The shared worker body is the
same as the accepted runner; control and database binding survive every phase.
"""
from contextlib import ExitStack
from datetime import datetime
import os
from pathlib import Path
import stat
from time import monotonic

from app.sqlite_isolated_lifecycle_runner import isolated_runner_lock
from app.sqlite_scheduled_configured_slot import _configured_run_inputs
from app.sqlite_scheduled_clock_checkpoint import _validate_clock_preparation
from app.sqlite_scheduled_paths import _canonical, _open_directory
from app.sqlite_scheduled_routed_slot import _run_routed_slot_locked
from app.sqlite_scheduled_slot import _claim_scheduled_slot_locked


def run_disposable_worker_layout(*, lab_root, control_root, settings, scheduled_at,
        now, clock=datetime.now, timer=monotonic, maximum_run_seconds=3600):
    """Only fresh marked labs: separate control/state.db from all media roots.

    Both the outer lab and its control directory require the established exact
    disposable marker. Existing database only; no bootstrap, migration or replay.
    The control lock retains its inode and pins database/marker identity; held
    ancestors and repeated opens reject control/outer replacement and aliases.
    """
    lab = Path(_canonical(str(lab_root)))
    control = Path(_canonical(str(control_root)))
    config, scan, protect = _configured_run_inputs(settings=settings, clock=clock)
    _validate_clock_preparation(root=lab, config=config, fetch_signals=scan, clock=clock,
        timer=timer, maximum_scan_seconds=maximum_run_seconds)
    if lab not in control.parents:
        raise ValueError('Control directory must be inside the disposable lab')
    for library in config.libraries:
        for _, path in library.roots:
            media = Path(path)
            if (lab not in media.parents or media == control or control in media.parents
                    or media in control.parents):
                raise ValueError('Media and control roots must be disjoint inside the lab')
    started = timer()
    with ExitStack() as stack:
        held = {}
        for path in (lab, control):
            fd = _open_directory(str(path)); stack.callback(os.close, fd)
            held[path] = os.fstat(fd)
        # Pin the outer marker independently; the control marker is pinned by
        # isolated_runner_lock below. No state file is expected in the outer lab.
        marker_fd = os.open(lab / '.sqlite_disposable_rehearsal',
                            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        stack.callback(os.close, marker_fd)
        marker = os.fstat(marker_fd)
        def verify_layout():
            for path, expected in held.items():
                fd = _open_directory(str(path))
                try:
                    actual = os.fstat(fd)
                    if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
                        raise RuntimeError('Disposable worker layout changed')
                finally:
                    os.close(fd)
            current = os.stat(lab / '.sqlite_disposable_rehearsal', follow_symlinks=False)
            if (not stat.S_ISREG(current.st_mode) or current.st_nlink != 1
                    or (current.st_dev, current.st_ino) != (marker.st_dev, marker.st_ino)
                    or os.pread(marker_fd, 17, 0) != b'DISPOSABLE ONLY\n'):
                raise RuntimeError('Disposable worker layout marker changed')
        verify_layout()
        with isolated_runner_lock(control) as verify_control:
            def verify_binding():
                verify_layout(); verify_control()
            with _claim_scheduled_slot_locked(root=control, schedule=config.schedule,
                    scheduled_at=scheduled_at, now=now, verify_binding=verify_binding) as verify_claim:
                result = _run_routed_slot_locked(database=control / 'state.db', config=config,
                    scheduled_at=scheduled_at, fetch_signals=scan, fetch_protection=protect,
                    arr_sync_requests=None, clock=clock, timer=timer, maximum_titles=100000,
                    maximum_run_seconds=maximum_run_seconds, maximum_protection_seconds=30,
                    verify_claim=verify_claim, started_tick=started)
                return {**result, 'layout': 'separate_control_and_media'}
