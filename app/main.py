import os
import threading

from collection_auditor import RUN_INTERVAL_HOURS, run_with_alerts
from web import app


WEB_PORT = int(os.environ.get("WEB_PORT", "8080"))


def start_web():
    app.run(host="0.0.0.0", port=WEB_PORT, debug=False, use_reloader=False)


if __name__ == "__main__":
    web_thread = threading.Thread(target=start_web, name="web-ui", daemon=True)
    web_thread.start()

    if RUN_INTERVAL_HOURS <= 0:
        run_with_alerts()
    else:
        print(f"Loop mode: running every {RUN_INTERVAL_HOURS} hours.")
        import time
        while True:
            try:
                run_with_alerts()
            except (Exception, SystemExit):
                pass
            print(f"Sleeping {RUN_INTERVAL_HOURS} hours until the next run.")
            time.sleep(RUN_INTERVAL_HOURS * 3600)
