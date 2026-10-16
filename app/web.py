import json
import os
import hmac
import requests
import posixpath
import re
import time
import threading
from datetime import timedelta
from datetime import datetime
from urllib.parse import urlsplit
from pathlib import Path
from flask import Flask, render_template, request, Response, redirect, url_for, session, g, send_file

from connection_tests import check_connection, SERVICES
from audit_history import read_history
from manual_rescue import rescue_title
from auth import session_key, jellyfin_login, current_user, store_token, discard_token, verify_user
from run_control import snapshot, request_run
from config_store import FIELDS, KEYS, SECRETS, BOOLS, DEFAULTS, FIELD_HELP, load_config, save_config, validate

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
        return render_template("login.html", error=None)
    origin = request.headers.get("Origin") or request.headers.get("Referer")
    if not origin or urlsplit(origin).netloc != request.host:
        return Response("Invalid request origin.", 403)
    username = request.form.get("username", "")[:128]
    password = request.form.get("password", "")
    if not username or not password:
        return render_template("login.html", error="Enter a username and password."), 400
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
        return render_template("login.html", error=login_error or "Invalid credentials for the local administrator account."), 401
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


# Cache Jellyfin's folder-to-image mapping to avoid a library scan per poster.
_POSTER_INDEX = {}
_POSTER_LOCK = threading.Lock()
_POSTER_TTL = 300


def _poster_headers(token):
    """Use the same Jellyfin authorization headers as connection_tests."""
    return {"X-Emby-Token": token, "Authorization": f'MediaBrowser Token="{token}"'}


def _poster_folder(item, media_type):
    path = (item.get("Path") or "").replace("\\", "/").rstrip("/")
    if not path:
        return ""
    if media_type == "Movie":
        return posixpath.basename(posixpath.dirname(path)).casefold()
    return posixpath.basename(path).casefold()


def _poster_index(base, token, media_type):
    """Match tracked folder names to Jellyfin IDs, like the auditor does."""
    key = (base, token, media_type)
    with _POSTER_LOCK:
        cached = _POSTER_INDEX.get(key)
        if cached and time.monotonic() - cached[0] < _POSTER_TTL:
            return cached[1]
    headers = _poster_headers(token)
    # Jellyfin API keys can enumerate users; use the same per-user items
    # endpoint as collection_auditor.get_signals().
    users_response = requests.get(base + "/Users", headers=headers, timeout=(3, 10),
                                  allow_redirects=False)
    users_response.raise_for_status()
    users = users_response.json()
    if not isinstance(users, list) or not users:
        return {}
    index = {}
    for user in users:
        user_id = user.get("Id")
        if not user_id:
            continue
        response = requests.get(base + "/Users/" + user_id + "/Items",
                                params={"Recursive": "true", "IncludeItemTypes": media_type,
                                        "Fields": "Path", "EnableImages": "true"},
                                headers=headers, timeout=(3, 15), allow_redirects=False)
        response.raise_for_status()
        for item in response.json().get("Items", []):
            if item.get("Type") != media_type or not item.get("Id"):
                continue
            # Do not require ImageTags here: some Jellyfin responses omit them.
            folder = _poster_folder(item, media_type)
            if folder:
                index.setdefault(folder, item["Id"])
            name = (item.get("Name") or "").strip().casefold()
            if name:
                index.setdefault("name:" + name, item["Id"])
    with _POSTER_LOCK:
        _POSTER_INDEX[key] = (time.monotonic(), index)
    return index


@app.get("/api/poster")
def poster():
    """Serve matching Jellyfin artwork without exposing API credentials."""
    title = request.args.get("title", "").strip()
    library = request.args.get("library", "")
    if not title or len(title) > 250 or library not in ("Movies", "TV"):
        return Response(status=400)
    config = load_config()
    base = config.get("JELLYFIN_HOST_URL", os.environ.get("JELLYFIN_HOST_URL", "")).rstrip("/")
    token = config.get("JELLYFIN_API_TOKEN", os.environ.get("JELLYFIN_API_TOKEN", "")).strip()
    if not base.startswith(("http://", "https://")) or not token:
        return Response(status=404)
    media_type = "Movie" if library == "Movies" else "Series"
    try:
        index = _poster_index(base, token, media_type)
        normalized = title.casefold()
        # Folder is authoritative; only fall back to a display-title match.
        display_name = re.sub(r"\\s*\\(\\d{4}\\)\\s*$", "", title).strip().casefold()
        item_id = (index.get(normalized) or index.get("name:" + normalized)
                   or index.get("name:" + display_name))
        if not item_id:
            return Response(status=404)
        image = requests.get(base + "/Items/" + item_id + "/Images/Primary",
                             params={"maxWidth": 200, "quality": 75},
                             headers=_poster_headers(token), timeout=(3, 8),
                             allow_redirects=False)
        if image.status_code != 200 or not image.headers.get("Content-Type", "").lower().startswith("image/"):
            return Response(status=404)
        return Response(image.content, mimetype=image.headers["Content-Type"],
                        headers={"Cache-Control": "private, max-age=3600"})
    except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError):
        app.logger.warning("Jellyfin poster lookup failed for %s", library, exc_info=True)
        return Response(status=404)


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
