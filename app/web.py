import json
import os
from pathlib import Path
from flask import Flask, render_template

app = Flask(__name__)

ACTION_LOG_FILE = os.environ.get("ACTION_LOG_FILE", "/app/logs/auditor_actions.jsonl")
STATE_FILE = os.environ.get("STATE_FILE", "/app/logs/auditor_state.json")


def load_actions(limit=250):
    path = Path(ACTION_LOG_FILE)
    if not path.exists():
        return []
    actions = []
    try:
        with path.open() as handle:
            for line in handle:
                try:
                    actions.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return list(reversed(actions[-limit:]))


def load_state():
    path = Path(STATE_FILE)
    if not path.exists():
        return {}
    try:
        with path.open() as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}


@app.get("/")
def dashboard():
    actions = load_actions()
    state = load_state()
    return render_template("dashboard.html", actions=actions, state=state)


@app.get("/logs")
def logs():
    return render_template("logs.html", actions=load_actions(1000))


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("WEB_PORT", "8080")))
