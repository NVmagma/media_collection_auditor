import json
import os
import hmac
from datetime import timedelta
from datetime import datetime
from urllib.parse import urlsplit
from pathlib import Path
from flask import Flask, render_template, request, Response, redirect, url_for, session, g, render_template_string, send_file

from connection_tests import check_connection, SERVICES
from audit_history import read_history
from manual_rescue import rescue_title
from auth import session_key, jellyfin_login, current_user, store_token, discard_token, verify_user
from run_control import snapshot, request_run
from config_store import FIELDS, KEYS, SECRETS, BOOLS, DEFAULTS, FIELD_HELP, load_config, save_config, validate

LOGIN_PAGE = "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Sign In · Media Collection Auditor</title><style>\n*{box-sizing:border-box}html,body{margin:0;min-height:100%;font-family:Inter,system-ui,-apple-system,sans-serif;color:#f2f6ff;background:#06101d}\n.login-scene{min-height:100dvh;background-image:linear-gradient(180deg,rgba(3,8,18,.04) 0%,rgba(3,8,18,.1) 45%,rgba(3,8,18,.6) 100%),url('/login-background');background-position:center center;background-size:cover;display:flex;align-items:flex-end;justify-content:center;padding:24px 20px 1vh}\n.login-panel{width:min(100%,530px);padding:18px 26px 18px;border:1px solid #48759e;border-radius:15px;background:rgba(5,14,27,.9);box-shadow:0 20px 70px #000a;backdrop-filter:blur(14px)}\nh1{text-align:center;font-size:23px;margin:0 0 8px}p.subtitle{text-align:center;font-size:13px;color:#b6c7da;margin:0 0 14px}\nlabel{display:block;font-size:13px;margin:10px 0 6px;color:#c5d6e9}input{display:block;width:100%;background:#0b1a2a;color:white;border:1px solid #536b85;border-radius:9px;padding:14px;font:inherit}input:focus{outline:2px solid #1b91f5;outline-offset:1px}button{display:block;width:100%;border:0;border-radius:9px;margin-top:14px;padding:13px;background:linear-gradient(#168eff,#0068d3);font-weight:700;color:white;font-size:16px;cursor:pointer}button:hover{filter:brightness(1.12)}.error{padding:12px;border:1px solid #c56a6a;background:#451b2a;border-radius:8px;font-size:13px}.note{font-size:12px;color:#9cb0c5;text-align:center;margin-top:15px}\n@media(max-width:650px){.login-scene{background-position:center top;padding:18px 12px 3vh}.login-panel{padding:20px 18px}h1{font-size:20px}}\n</style></head><body><main class=\"login-scene\"><section class=\"login-panel\"><h1>Sign in with Jellyfin</h1><p class=\"subtitle\">Use your Jellyfin account to access Media Collection Auditor.</p>{% if error %}<p class=\"error\" role=\"alert\">{{ error }}</p>{% endif %}<form method=\"post\" action=\"/login\"><label for=\"username\">Username</label><input id=\"username\" name=\"username\" autocomplete=\"username\" maxlength=\"128\" required autofocus><label for=\"password\">Password</label><input id=\"password\" name=\"password\" type=\"password\" autocomplete=\"current-password\" required><button type=\"submit\">Sign In</button></form><p class=\"note\">Jellyfin administrators can manage settings and rescue titles.</p></section></main></body></html>"
app = Flask(__name__)
app.secret_key = session_key()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=os.environ.get("WEB_SECURE_COOKIE", "false").lower() == "true",
                  PERMANENT_SESSION_LIFETIME=timedelta(hours=12))

@app.before_request
def require_login():
    if request.endpoint in ("login", "login_background", "health", "static"):
        return None
    g.user = current_user()
    if g.user is None:
        if request.path.startswith("/api/"):
            return {"ok": False, "message": "Please sign in."}, 401
        return redirect(url_for("login"))
    if request.endpoint in ("settings", "test_connection", "run_now", "rescue") and not g.user["admin"]:
        if request.path.startswith("/api/"):
            return {"ok": False, "message": "Administrator access required."}, 403
        return Response("Administrator access required.", 403)

@app.context_processor
def user_context():
    return {"viewer": getattr(g, "user", None)}

@app.get("/login-background")
def login_background():
    path = Path(os.environ.get("WEB_LOGIN_IMAGE_FILE", "/app/logs/login-background.jpg"))
    if path.is_file():
        return send_file(path, mimetype="image/jpeg", max_age=3600)
    return Response(status=404)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if current_user():
            return redirect(url_for("dashboard"))
        return render_template_string(LOGIN_PAGE, error=None)
    origin = request.headers.get("Origin") or request.headers.get("Referer")
    if not origin or urlsplit(origin).netloc != request.host:
        return Response("Invalid request origin.", 403)
    username = request.form.get("username", "")[:128]
    password = request.form.get("password", "")
    if not username or not password:
        return render_template_string(LOGIN_PAGE, error="Enter a username and password."), 400
    user, login_error = jellyfin_login(username, password)
    if user and not verify_user(user["token"], user["id"]):
        user = None
        login_error = "Jellyfin authenticated you, but the account could not be verified. Check Jellyfin permissions and the server URL."
    discard_token(session.get("jf_handle"))
    session.clear()
    if user:
        session.update(provider="jellyfin", jf_handle=store_token(user["token"], user["id"]))
    elif (os.environ.get("WEB_ADMIN_PASSWORD")
          and hmac.compare_digest(username, os.environ.get("WEB_ADMIN_USER", "admin"))
          and hmac.compare_digest(password, os.environ["WEB_ADMIN_PASSWORD"])):
        session["provider"] = "local"
    else:
        return render_template_string(LOGIN_PAGE, error=login_error or "Invalid credentials for the local administrator account."), 401
    session.permanent = True
    return redirect(url_for("dashboard"))

@app.post("/logout")
def logout():
    origin = request.headers.get("Origin") or request.headers.get("Referer")
    if not origin or urlsplit(origin).netloc != request.host:
        return Response("Invalid request origin.", 403)
    discard_token(session.get("jf_handle"))
    session.clear()
    return redirect(url_for("login"))


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
    removal_days = int(load_config().get("REMOVAL_DAYS", os.environ.get("REMOVAL_DAYS", "7")))
    for item in stages["Removal"]:
        try:
            age = (datetime.now() - datetime.fromisoformat(item["since"])).days
            item["days_left"] = max(0, removal_days - age)
        except (ValueError, TypeError):
            item["days_left"] = None
    return render_template("dashboard.html", actions=actions, state=state, stages=stages, run=snapshot(), history=read_history(100),
                           dry_run=load_config().get("DRY_RUN", os.environ.get("DRY_RUN", "true")).lower() == "true")


@app.get("/logs")
def logs():
    return render_template("logs.html", actions=load_actions(1000))


def admin_authorized():
    return bool(getattr(g, "user", None) and g.user["admin"])


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


@app.post("/api/rescue")
def rescue():
    if not admin_authorized():
        return {"ok": False, "message": "Sign in through Settings first."}, 401
    origin = request.headers.get("Origin") or request.headers.get("Referer")
    if not origin or urlsplit(origin).netloc != request.host:
        return {"ok": False, "message": "Invalid request origin."}, 403
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return {"ok": False, "message": "Invalid request."}, 400
    ok, message, status = rescue_title(data.get("library"), data.get("title"), data.get("destination"))
    return {"ok": ok, "message": message}, status


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("WEB_PORT", "8080")))
