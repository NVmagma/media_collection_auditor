"""Run the dashboard and auditor; load saved web settings before every audit."""
import importlib
import os
import threading
import time

from config_store import KEYS, load_config
from web import app

WEB_PORT = int(os.environ.get("WEB_PORT", "8080"))
BASE_ENV = {key: os.environ.get(key) for key in KEYS}


def apply_settings():
    # Restore Unraid's original environment first so removing an override works.
    for key, value in BASE_ENV.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    os.environ.update(load_config())


def start_web():
    app.run(host="0.0.0.0", port=WEB_PORT, debug=False, use_reloader=False)


if __name__ == "__main__":
    web_thread = threading.Thread(target=start_web, name="web-ui", daemon=True)
    web_thread.start()
    auditor = None
    while True:
        apply_settings()
        # The auditor reads its configuration at import time. Reload it before
        # each run so web changes take effect without restarting the container.
        if auditor is None:
            import collection_auditor as auditor
        else:
            auditor = importlib.reload(auditor)
        interval = auditor.RUN_INTERVAL_HOURS
        try:
            auditor.run_with_alerts()
        except (Exception, SystemExit) as exc:
            print(f"[AUDITOR ERROR] {exc}", flush=True)
        if interval <= 0:
            # Keep the web UI alive even when configured for a single audit.
            threading.Event().wait()
        print(f"Sleeping {interval} hours until the next run.", flush=True)
        time.sleep(interval * 3600)
