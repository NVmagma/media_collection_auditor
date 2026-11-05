"""Best-effort process-local observations; never scan or replay authority."""
from contextlib import contextmanager
from contextvars import ContextVar

PHASES = {
    'starting': 'Starting scan',
    'inventory': 'Inspecting media folders',
    'jellyfin': 'Checking Jellyfin protection',
    'arr': 'Checking Radarr / Sonarr records',
    'planning': 'Evaluating lifecycle decisions',
    'revalidation': 'Rechecking inventory',
    'execution': 'Applying verified actions',
    'saving': 'Saving recorded results',
}
_sink = ContextVar('scan_progress_sink', default=None)


@contextmanager
def observe(callback):
    token = _sink.set(callback)
    try:
        yield
    finally:
        _sink.reset(token)


def emit(phase, *, checked=None, total=None, library=None):
    if phase not in PHASES or library not in (None, 'Movies', 'TV'):
        return
    if any(value is not None and (type(value) is not int or not 0 <= value <= 100000)
           for value in (checked, total)):
        return
    if checked is not None and total is not None and checked > total:
        return
    callback = _sink.get()
    if callback is not None:
        try:
            callback(dict(phase=phase, label=PHASES[phase], checked=checked, total=total, library=library))
        except Exception:
            pass  # Display instrumentation must never change a worker outcome.
