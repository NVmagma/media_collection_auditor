"""Run dashboard and serialized audits with persistent web settings."""
import importlib
import json
import os
import threading

from config_store import KEYS, load_config
from audit_history import new_record, finish_record, summarize_actions
from run_control import begin_run, finish_run, wait_for_run
from web import app
from integration_api import read_only_service_enabled

WEB_PORT = int(os.environ.get("WEB_PORT", "8080"))
BASE_ENV = {key: os.environ.get(key) for key in KEYS}


def apply_settings():
    for key, value in BASE_ENV.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    os.environ.update(load_config())


def start_web():
    app.run(host="0.0.0.0", port=WEB_PORT, debug=False, use_reloader=False)


def audit_counts(path, offset):
    """Count distinct movie/TV folders in this run's action log (not API scan totals)."""
    seen = {"Movies": set(), "TV": set()}
    try:
        with open(path, encoding="utf-8") as handle:
            handle.seek(offset)
            for line in handle:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                library, folder = event.get("library"), event.get("folder")
                if library in seen and folder and folder != "-":
                    seen[library].add(folder)
    except OSError:
        pass
    return len(seen["Movies"]), len(seen["TV"])


if __name__ == "__main__":
    if read_only_service_enabled():
        start_web()
        raise SystemExit(0)
    threading.Thread(target=start_web, name="web-ui", daemon=True).start()
    auditor = None
    while True:
        interval = 0
        record = None
        started = False
        log_path = os.environ.get("ACTION_LOG_FILE", "/app/logs/auditor_actions.jsonl")
        offset = os.path.getsize(log_path) if os.path.exists(log_path) else 0
        result = "completed"
        error = None
        try:
            apply_settings()
            auditor = importlib.import_module("collection_auditor") if auditor is None else importlib.reload(auditor)
            interval = auditor.RUN_INTERVAL_HOURS
            log_path = auditor.ACTION_LOG_FILE
            offset = os.path.getsize(log_path) if os.path.exists(log_path) else 0
            trigger = begin_run(auditor.DRY_RUN)
            started = True
            record = new_record(trigger, auditor.DRY_RUN)
            auditor.run_with_alerts()
        except (Exception, SystemExit) as exc:
            result = "failed"
            error = f"{type(exc).__name__}: {str(exc)[:200]}"
            print(f"[AUDITOR ERROR] {error}", flush=True)
        finally:
            summary = summarize_actions(log_path, offset)
            if record is None:
                # Configuration errors are recorded too, without assuming a run began.
                trigger = begin_run(os.environ.get("DRY_RUN", "true").lower() == "true") if not started else "scheduled"
                record = new_record(trigger, os.environ.get("DRY_RUN", "true").lower() == "true")
            try:
                finish_record(record, result, summary, error)
            except OSError as exc:
                print(f"[HISTORY ERROR] {exc}", flush=True)
            finish_run(result, summary["movies_processed"], summary["tv_processed"], interval)
        print(f"[SCHEDULER] Waiting for next run ({interval} hours; manual runs available).", flush=True)
        wait_for_run(interval * 3600 if interval > 0 else None)
