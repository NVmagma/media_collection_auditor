import json
import os
import hmac
from urllib.parse import urlsplit
from pathlib import Path
from flask import Flask, render_template, request, Response, redirect, url_for

from connection_tests import check_connection, SERVICES
from audit_history import read_history
from run_control import snapshot, request_run
from config_store import FIELDS, KEYS, SECRETS, BOOLS, DEFAULTS, FIELD_HELP, load_config, save_config, validate

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
    stages = {}
    for label, section in (("Waiting", "first_seen"), ("Holding", "queued"), ("Removal", "in_removal"), ("Keep", "keep_seen")):
        records = state.get(section, {})
        stages[label] = [{"title": key[3:] if key.startswith("TV/") else key,
                          "library": "TV" if key.startswith("TV/") else "Movies",
                          "since": since} for key, since in records.items()]
    return render_template("dashboard.html", actions=actions, state=state, stages=stages, run=snapshot(), history=read_history(100),
                           dry_run=load_config().get("DRY_RUN", os.environ.get("DRY_RUN", "true")).lower() == "true")


@app.get("/logs")
def logs():
    return render_template("logs.html", actions=load_actions(1000))


def admin_authorized():
    password = os.environ.get("WEB_ADMIN_PASSWORD", "")
    username = os.environ.get("WEB_ADMIN_USER", "admin")
    auth = request.authorization
    return bool(password and auth and auth.type == "basic"
                and hmac.compare_digest(auth.username or "", username)
                and hmac.compare_digest(auth.password or "", password))


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if not admin_authorized():
        return Response("Settings require WEB_ADMIN_PASSWORD (and HTTP Basic authentication).",
                        401, {"WWW-Authenticate": 'Basic realm="Auditor settings"'})
    saved = load_config()
    error = None
    success = request.args.get("saved") == "1"
    if request.method == "POST":
        # Reject cross-origin browser submissions; don't accept unauthenticated writes.
        origin = request.headers.get("Origin") or request.headers.get("Referer")
        if not origin or urlsplit(origin).netloc != request.host:
            return Response("Invalid request origin", 403)
        updated = dict(saved)
        try:
            for key in KEYS:
                raw = request.form.get(key, "").strip()
                if key in SECRETS and not raw:
                    continue  # Empty password field preserves existing secret.
                if not raw and key not in BOOLS:
                    updated.pop(key, None)  # Fall back to Unraid environment.
                else:
                    updated[key] = validate(key, raw)
            if (updated.get("DRY_RUN", os.environ.get("DRY_RUN", "true")).lower() == "false"
                    or updated.get("ALLOW_FILESYSTEM_DELETE", "false") == "true"
                    or updated.get("ALLOW_CROSS_FILESYSTEM_MOVES", "false") == "true"
                    or updated.get("ENABLE_SEASON_PRUNING", "false") == "true"):
                if request.form.get("safety_confirmation") != "I UNDERSTAND":
                    raise ValueError("Type I UNDERSTAND to confirm potentially destructive settings.")
            save_config(updated)
            return redirect(url_for("settings", saved=1))
        except (ValueError, OSError) as exc:
            error = str(exc)
    values = {key: saved.get(key, os.environ.get(key, DEFAULTS.get(key, "")))
              for key in KEYS}
    sources = {key: ("Web override" if key in saved else
                     "Unraid" if key in os.environ else "Default") for key in KEYS}
    for key in SECRETS:
        values[key] = ""  # Never send stored tokens to the browser.
    return render_template("settings.html", groups=FIELDS, values=values,
                           secrets=SECRETS, bools=BOOLS, sources=sources, help_text=FIELD_HELP, error=error,
                           success=success)


@app.post("/api/test-connection/<service>")
def test_connection(service):
    if not admin_authorized():
        return {"ok": False, "message": "Authentication required."}, 401
    origin = request.headers.get("Origin") or request.headers.get("Referer")
    if not origin or urlsplit(origin).netloc != request.host:
        return {"ok": False, "message": "Invalid request origin."}, 403
    if service not in SERVICES:
        return {"ok": False, "message": "Unknown service."}, 404
    return check_connection(service)


@app.post("/api/run-now")
def run_now():
    if not admin_authorized():
        return {"ok": False, "message": "Authentication required."}, 401
    origin = request.headers.get("Origin") or request.headers.get("Referer")
    if not origin or urlsplit(origin).netloc != request.host:
        return {"ok": False, "message": "Invalid request origin."}, 403
    if request_run():
        return {"ok": True, "message": "Audit queued. Refresh the dashboard for results."}, 202
    return {"ok": False, "message": "An audit is already running or queued."}, 409


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("WEB_PORT", "8080")))
