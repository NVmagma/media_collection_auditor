"""Single-run coordinator shared by Flask and the audit worker."""
import threading
from datetime import datetime, timedelta, timezone

_lock = threading.Lock()
_wake = threading.Event()
_status = {"running": False, "queued": False, "last_started": None, "last_finished": None,
           "last_result": None, "next_run": None, "movies_processed": None,
           "tv_processed": None, "dry_run": None}

def snapshot():
    with _lock:
        return dict(_status)

def request_run():
    with _lock:
        if _status["running"] or _status["queued"]:
            return False
        _status["queued"] = True
    _wake.set()
    return True

def begin_run(dry_run):
    with _lock:
        _status.update(running=True, queued=False, last_started=datetime.now(timezone.utc).isoformat(),
                       last_result=None, next_run=None, dry_run=dry_run)
    _wake.clear()

def finish_run(result, movies, tv, interval):
    now = datetime.now(timezone.utc)
    with _lock:
        _status.update(running=False, last_finished=now.isoformat(), last_result=result,
                       movies_processed=movies, tv_processed=tv,
                       next_run=(now + timedelta(hours=interval)).isoformat() if interval > 0 else None)

def wait_for_run(timeout):
    triggered = _wake.wait(timeout)
    _wake.clear()
    return triggered
