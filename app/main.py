"""Run dashboard and serialized audits with persistent web settings."""
import importlib
import json
import os
import threading

from config_store import KEYS, load_config
from run_control import begin_run, finish_run, wait_for_run
from web import app

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
    threading.Thread(target=start_web, name="web-ui", daemon=True).start()
    auditor = None
    while True:
        apply_settings()
        try:
            auditor = importlib.import_module("collection_auditor") if auditor is None else importlib.reload(auditor)
            interval = auditor.RUN_INTERVAL_HOURS
            log_path = auditor.ACTION_LOG_FILE
            offset = os.path.getsize(log_path) if os.path.exists(log_path) else 0
            begin_run(auditor.DRY_RUN)
            result = "completed"
            try:
                auditor.run_with_alerts()
            except (Exception, SystemExit) as exc:
                result = "failed"
                print(f"[AUDITOR ERROR] {exc}", flush=True)
            movies, tv = audit_counts(log_path, offset)
            finish_run(result, movies, tv, interval)
        except (Exception, SystemExit) as exc:
            print(f"[CONFIG ERROR] {exc}", flush=True)
            # Never start an audit using stale configuration after reload failure.
            finish_run("failed", 0, 0, 0)
            interval = 0
        print(f"[SCHEDULER] Waiting for next run ({interval} hours; manual runs available).", flush=True)
        wait_for_run(interval * 3600 if interval > 0 else None)
