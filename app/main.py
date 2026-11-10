"""Run dashboard and serialized audits with persistent web settings."""
import importlib
import json
import os
import threading

from config_store import KEYS, load_config
from audit_history import new_record, finish_record, summarize_actions
from run_control import begin_run, finish_run, wait_for_run
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
    from web import app  # Scan readiness is checked separately from UI availability.
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
    from app.unraid_setup import prepare_installation
    from backend_selection import require_json_backend
    require_json_backend(os.environ.get('AUDITOR_STATE_BACKEND','json'))
    os.environ.setdefault('AUDITOR_WORKER_MODE','json_serialized')
    if not read_only_service_enabled(): prepare_installation()
    if read_only_service_enabled():
        start_web()
    else:
        from app.json_worker_service import run_service
        threading.Thread(target=start_web,name='web-ui',daemon=True).start()
        try:
            run_service()
        except KeyboardInterrupt:
            pass
