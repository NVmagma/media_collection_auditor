"""Single-run coordinator shared by Flask and the audit worker."""
import threading
import time
from datetime import datetime, timedelta, timezone
from audit_history import read_history

_lock = threading.Lock()
_wake = threading.Event()
_status = {"running": False, "rescuing": False, "queued": False, "last_started": None, "last_finished": None,
           "last_result": None, "next_run": None, "movies_processed": None,
           "tv_processed": None, "dry_run": None}

def snapshot():
    with _lock:
        current = dict(_status)
    history = read_history(1)
    if history and not current["running"]:
        latest = history[0]
        current["last_started"] = latest.get("started_at")
        current["last_finished"] = latest.get("finished_at")
        current["last_result"] = latest.get("result")
        current["movies_processed"] = latest.get("movies_processed")
        current["tv_processed"] = latest.get("tv_processed")
    return current

def request_run():
    with _lock:
        if _status["running"] or _status["rescuing"] or _status["queued"]:
            return False
        _status["queued"] = True
    _wake.set()
    return True

def begin_run(dry_run):
    # Claim the run only after any manual rescue has finished.
    while True:
        with _lock:
            if not _status["rescuing"]:
                trigger = "manual" if _status["queued"] else "scheduled"
                _status.update(running=True, queued=False, last_started=datetime.now(timezone.utc).isoformat(),
                               last_result=None, next_run=None, dry_run=dry_run)
                break
        time.sleep(0.1)
    _wake.clear()
    return trigger

def finish_run(result, movies, tv, interval):
    now = datetime.now(timezone.utc)
    with _lock:
        _status.update(running=False, last_finished=now.isoformat(), last_result=result,
                       movies_processed=movies, tv_processed=tv,
                       next_run=(now + timedelta(hours=interval)).isoformat() if interval > 0 else None)

def wake_worker():
    """Wake the worker without creating a legacy JSON audit request."""
    _wake.set()

def wait_for_run(timeout):
    triggered = _wake.wait(timeout)
    _wake.clear()
    return triggered

def begin_rescue():
    with _lock:
        if _status["running"] or _status["rescuing"] or _status["queued"]:
            return False
        _status["rescuing"] = True
        return True

def end_rescue():
    with _lock:
        _status["rescuing"] = False
