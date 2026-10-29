import json
import os
import hmac
import requests
import posixpath
import re
import time
import threading
import io
import zipfile
from urllib.parse import quote
from datetime import timedelta
from datetime import datetime
from urllib.parse import urlsplit
from pathlib import Path
from flask import Flask, render_template, request, Response, redirect, url_for, session, g, send_file

from lifecycle_decisions import decide
from dashboard_tracking_snapshot import lifecycle_clock, observation_datetime, summarize_dashboard_clocks, dashboard_overview, build_scan_view
from connection_tests import check_connection, SERVICES
from audit_history import read_history
from manual_rescue import rescue_title
from auth import session_key, jellyfin_login, current_user, store_token, discard_token, verify_user
from run_control import snapshot, request_run
from config_store import FIELDS, KEYS, SECRETS, BOOLS, DEFAULTS, FIELD_HELP, load_config, save_config, validate, redacted_config
from integration_api import authorize_summary, read_only_service_enabled
from integration_status import (selected_backup_status, selected_scan_capture, project_scan_capture, read_selected_coverage, selected_run_snapshot, selected_run_history, selected_audit_status_report, audit_status_report, collect_widget_media_index, widget_media_urls, widget_media_base,
    read_selected_tracking_status as read_tracking_status,
    read_selected_tracking_titles as read_tracking_titles,
    read_selected_dashboard_state as read_dashboard_state)

app = Flask(__name__)
app.secret_key = os.urandom(32).hex() if read_only_service_enabled() else session_key()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=os.environ.get("WEB_SECURE_COOKIE", "false").lower() == "true",
                  PERMANENT_SESSION_LIFETIME=timedelta(hours=12))

def _preview_backend_gate():
    # Legacy JSON images copy modules flat; preview images include the app package.
    try:
        from app import sqlite_backend_gate
    except ModuleNotFoundError as error:
        if error.name != 'app':
            raise
        import sqlite_backend_gate
    return sqlite_backend_gate


@app.before_request
def require_login():
    gate = _preview_backend_gate()
    preview = gate.preview_release_enabled()
    live = gate.live_release_enabled()
    if read_only_service_enabled() and not preview and request.endpoint not in (
            "integration_summary", "integration_audit_status", "integration_titles", "integration_readiness", "integration_coverage", "integration_scan_history", "integration_proposals", "integration_backup_status", "health"):
        return {"status": "read_only_service"}, 404
    if request.path.startswith("/api/v1/"):
        failure = authorize_summary(request.headers.get("Authorization"))
        if failure is not None: return failure
        if request.endpoint is None and getattr(request.routing_exception, "code", None) == 404:
            return {"status": "route_not_found", "schema_version": 1,
                    "message": "Unknown integration route. See /api/v1/readiness for supported routes."}, 404
    if request.endpoint in ("integration_readiness", "integration_backup_status"):
        return None
    if request.endpoint in ("integration_summary", "integration_audit_status", "integration_titles", "integration_coverage", "integration_scan_history", "integration_proposals"):
        if preview or live:
            try: (gate.require_sqlite_read_authority if live else gate.require_sqlite_production_activation)()
            except RuntimeError:
                return {"status":"live_paused" if live else "preview_paused", "read_only":True, "media_actions_authorized":False,
                        "message":"Scheduled scans are paused; settings or tracking need review."}, 503
        return None
    if request.endpoint in ("login", "login_background", "health", "static"):
        return None
    g.user = current_user()
    if g.user is None:
        if request.path.startswith("/api/"):
            return {"ok": False, "message": "Please sign in."}, 401
        return redirect(url_for("login"))
    if (preview or live) and request.endpoint not in ('settings','logout','run_now','apply_preview_settings','restore_preview_settings','integration_setup'):
        try: (gate.require_sqlite_read_authority if live else gate.require_sqlite_production_activation)()
        except RuntimeError:
            if request.path.startswith('/api/'):
                return {'status':'live_paused' if live else 'preview_paused','media_actions_authorized':False}, 503
            return render_template('preview-paused.html', live_mode=live), 503
    if request.endpoint in ("settings", "test_connection", "run_now", "rescue", "apply_preview_settings", "restore_preview_settings", "integration_setup") and not g.user["admin"]:
        if request.path.startswith("/api/"):
            return {"ok": False, "message": "Administrator access required."}, 403
        return Response("Administrator access required.", 403)

@app.context_processor
def user_context():
    return {"viewer": getattr(g, "user", None),
            "experimental_sqlite_recovery_enabled": (
                os.environ.get("EXPERIMENTAL_SQLITE_RECOVERY_VIEW", "").lower() == "true"
                and "experimental_sqlite_recovery_view" in app.blueprints
            )}

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


@app.after_request
def integration_response_headers(response):
    if request.path.startswith("/api/v1/") or request.endpoint == "integration_setup":
        response.headers["Cache-Control"] = "no-store"
        response.headers["Vary"] = "Authorization"
        response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def _integration_readiness():
    """Selected tracking readiness; no remote collection or credential projection."""
    gate = _preview_backend_gate()
    preview = gate.preview_release_enabled()
    live = gate.live_release_enabled()
    binding = 'not_required'
    if preview or live:
        try:
            (gate.require_sqlite_read_authority if live else gate.require_sqlite_production_activation)()
            binding = 'verified'
        except RuntimeError:
            binding = 'review_required'
    report = None if binding == 'review_required' else read_tracking_status(STATE_FILE)
    available = isinstance(report, dict) and report.get('status') == 'advisory_only'
    return {
        'schema_version': 1, 'api_version': 'v1',
        'status': 'ready' if available else 'unavailable',
        'tracking_available': available, 'binding_status': binding,
        'storage_authority': os.environ.get('AUDITOR_STATE_BACKEND', 'json') if os.environ.get('AUDITOR_STATE_BACKEND', 'json') in ('json', 'sqlite') else 'unavailable',
        'freshness_verified': False, 'read_only': True,
        'media_actions_authorized': False,
        'execution_mode': 'scheduled_live_moves' if live else ('scheduled_preview' if preview else 'read_only_integration'),
        'title_details_enabled': os.environ.get('INTEGRATION_API_TITLE_DETAILS', 'false').lower() == 'true',
        'poster_lookup_enabled': os.environ.get('INTEGRATION_API_MEDIA', 'false').lower() == 'true',
        'coordinator_scope': 'unavailable' if read_only_service_enabled() else 'current_process',
        'routes': ['/api/v1/readiness', '/api/v1/summary', '/api/v1/audit-status',
                   '/api/v1/titles/oldest-waiting', '/api/v1/titles/leaving-soon', '/api/v1/coverage', '/api/v1/scan-history', '/api/v1/proposals', '/api/v1/backup-status'],
        'libraries': ['Movies', 'TV'], 'title_limit': 10,
        'backup_selection_configured': all(os.environ.get(key) for key in ('INTEGRATION_API_BACKUP_DIRECTORY', 'INTEGRATION_API_BACKUP_IDENTITY', 'INTEGRATION_API_BACKUP_FINGERPRINT')),
        'coverage_enabled': os.environ.get('INTEGRATION_API_COVERAGE', 'false').lower() == 'true',
    }


@app.get('/api/v1/readiness')
def integration_readiness():
    report = _integration_readiness()
    return report, 200 if report['status'] == 'ready' else 503


@app.get('/integrations')
def integration_setup():
    # Browser administrator only; integration credentials do not grant access.
    configured = authorize_summary(None)
    token_ready = configured is not None and configured[1] == 401
    return render_template('integrations.html', readiness=_integration_readiness(), token_ready=token_ready)


@app.get('/api/v1/backup-status')
def integration_backup_status():
    if request.args:
        return {'status':'invalid_query'}, 400
    report = selected_backup_status()
    return report, 200 if report['packet_verified'] else 503


def _scan_api_report():
    capture = None if read_only_service_enabled() else selected_scan_capture()
    return project_scan_capture(capture)


@app.get('/api/v1/scan-history')
def integration_scan_history():
    values = {}
    for key, default, maximum in (('page', '1', 100), ('page_size', '5', 20)):
        raw = request.args.get(key, default)
        if len(request.args.getlist(key)) > 1 or not re.fullmatch(r'[1-9][0-9]{0,2}', raw) or int(raw) > maximum:
            return {'status':'invalid_pagination'}, 400
        values[key] = int(raw)
    outcome = request.args.get('outcome', 'all')
    if outcome not in ('all','completed','review','unknown') or len(request.args.getlist('outcome')) > 1:
        return {'status':'invalid_outcome'}, 400
    report = _scan_api_report()
    rows = report.pop('rows')
    base = {**report, **values, 'outcome':outcome, 'pagination_scope':'current_capture',
            'retained_limit':100}
    if rows is None:
        return {**base, 'items':None, 'total_records':None, 'has_more':False}, 503
    rows = [row for row in rows if outcome == 'all' or row['group'] == outcome]
    start = (values['page'] - 1) * values['page_size']
    return {**base, 'items':rows[start:start+values['page_size']], 'total_records':len(rows),
            'has_more':start+values['page_size'] < len(rows)}, 200


@app.get('/api/v1/proposals')
def integration_proposals():
    report = _scan_api_report()
    rows = report.pop('rows')
    latest = rows[0] if rows else None
    verified = bool(latest and latest['group'] == 'completed' and latest['mode'] == 'Preview')
    return {**report, 'proposal_scope':'latest_recorded_attempt',
            'proposal_kind':'counts_only', 'latest_attempt':latest,
            'preview_completed':verified,
            'moves_proposed':latest['moves_proposed'] if verified else None,
            'discovery_changes':latest['discovery_changes'] if verified else None}, 503 if rows is None else 200


@app.get('/api/v1/coverage')
def integration_coverage():
    if os.environ.get('INTEGRATION_API_COVERAGE', 'false').lower() != 'true':
        return {'status':'disabled'}, 404
    library = request.args.get('library')
    if library not in (None, 'Movies', 'TV') or len(request.args.getlist('library')) > 1:
        return {'status':'invalid_library'}, 400
    base = {'schema_version':1, 'read_only':True, 'automatic_action':'none',
            'freshness_verified':False, 'media_actions_authorized':False,
            'observation_scope':'local_inventory_and_selected_tracking',
            'filesystem_snapshot_atomic':False}
    try:
        config = load_config()
        enabled = [name for name,key,fallback in (('Movies','ENABLE_MOVIES','true'),('TV','ENABLE_TV','false'))
                   if str(config.get(key,os.environ.get(key,fallback))).lower() == 'true']
        if library is not None and library not in enabled:
            return {**base, 'status':'library_disabled'}, 400
        if library is not None:
            enabled = [library]
        if not enabled:
            return {**base, 'status':'no_enabled_libraries', 'rows':[], 'complete':False}, 503
        inventory_config = {**config, 'ENABLE_MOVIES':str('Movies' in enabled).lower(),
                            'ENABLE_TV':str('TV' in enabled).lower()}
        def build(state):
            stages, warnings = filesystem_stages(state, inventory_config, max_entries=10000)
            result = summarize_dashboard_clocks(state, stages, warnings, libraries=enabled)
            # Incomplete aggregates are unknown; do not present partial totals as full coverage.
            if not result['complete']:
                for key in ('missing_dates','invalid_dates','future_dates','records_without_stage_folder'):
                    result[key] = None
            return result
        result = read_selected_coverage(STATE_FILE, build)
        if load_config() != config:
            raise RuntimeError('Settings changed during observation')
        return {**base, **result, 'status':'advisory_only' if result['complete'] else 'unavailable'}, 200 if result['complete'] else 503
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError):
        return {**base, 'status':'unavailable', 'rows':None, 'complete':False,
                'storage_authority':'unavailable', 'state_revision':None}, 503


@app.get("/api/v1/summary")
def integration_summary():
    report = read_tracking_status(STATE_FILE)
    return report, 503 if report["status"] == "unavailable" else 200


_WIDGET_MEDIA_CACHE = {}
_WIDGET_MEDIA_LOCK = threading.Lock()


def _widget_media_index(base, token, media_type):
    """Five-minute presentation cache; never used for lifecycle decisions."""
    if not widget_media_base(base) or not token:
        raise ValueError("Invalid media transport")
    key = (base, token, media_type)
    with _WIDGET_MEDIA_LOCK:
        cached = _WIDGET_MEDIA_CACHE.get(key)
        if cached and time.monotonic() - cached[0] < 300:
            return cached[1], "cached"
    deadline = time.monotonic() + 8

    def fetch(path, params):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("Media lookup deadline exceeded")
        response = requests.get(base + path, params=params, headers=_poster_headers(token),
                                timeout=(min(2, remaining), min(4, remaining)), allow_redirects=False)
        if response.status_code != 200:
            raise ValueError("Media lookup unavailable")
        data = response.json()
        if time.monotonic() > deadline:
            raise ValueError("Media lookup deadline exceeded")
        return data

    index = collect_widget_media_index(fetch, media_type)
    with _WIDGET_MEDIA_LOCK:
        if len(_WIDGET_MEDIA_CACHE) >= 4:
            _WIDGET_MEDIA_CACHE.clear()
        _WIDGET_MEDIA_CACHE[key] = (time.monotonic(), index)
    return index, "collected"


def _integration_title_media(report):
    if not isinstance(report.get("items"), list):
        return report
    enabled = os.environ.get("INTEGRATION_API_MEDIA", "false").lower() == "true"
    report["media_lookup_status"] = "disabled" if not enabled else "available"
    config = load_config() if enabled else {}
    base = config.get("JELLYFIN_HOST_URL", os.environ.get("JELLYFIN_HOST_URL", "")).rstrip("/")
    # Saved Settings wins for both transport and browser navigation by default.
    # An explicit override supports internal-only Docker names/reverse proxies.
    public = widget_media_base(os.environ.get("JELLYFIN_PUBLIC_URL", base))
    if enabled and not public:
        report["media_lookup_status"] = "unavailable"
    report["media_cache_max_age_seconds"] = 300 if enabled else None
    token = config.get("JELLYFIN_API_TOKEN", os.environ.get("JELLYFIN_API_TOKEN", ""))
    indexes = {}
    for item in report["items"]:
        library = item["library"]
        if enabled and public and library not in indexes:
            try:
                indexes[library], _ = _widget_media_index(base, token, "Movie" if library == "Movies" else "Series")
            except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError):
                indexes[library] = None
                report["media_lookup_status"] = "unavailable"
        item.update(widget_media_urls(item, indexes.get(library), public))
        if not enabled:
            item["match_status"] = "disabled"
    return report


@app.get("/api/v1/titles/oldest-waiting", defaults={"view": "oldest-waiting"})
@app.get("/api/v1/titles/leaving-soon", defaults={"view": "leaving-soon"})
def integration_titles(view):
    if os.environ.get("INTEGRATION_API_TITLE_DETAILS", "false").lower() != "true":
        return {"status": "disabled"}, 404
    library = request.args.get('library')
    if library not in (None, 'Movies', 'TV') or len(request.args.getlist('library')) > 1:
        return {'status': 'invalid_library'}, 400
    options = {} if library is None else {'library': library}
    days = 7
    if view == "leaving-soon":
        config = load_config()
        try:
            days = max(1, int(config.get("HOLDING_DAYS", os.environ.get("HOLDING_DAYS", "7"))))
        except (ValueError, TypeError):
            days = 0
    report = _integration_title_media(read_tracking_titles(STATE_FILE, view, holding_days=days, **options))
    return report, 503 if report["status"] == "unavailable" else 200


@app.get("/api/v1/audit-status")
def integration_audit_status():
    if read_only_service_enabled():
        report = audit_status_report(None)
        report["source"] = "coordinator_unavailable_in_read_only_service"
        return report, 503
    report = selected_audit_status_report(snapshot)
    return report, 503 if report["status"] == "unavailable" else 200


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
    return read_dashboard_state(STATE_FILE)



def _live_jellyfin_signals(config):
    """Read-only, short-lived tag/favorite snapshot; never authorizes filesystem actions."""
    base = config.get("JELLYFIN_HOST_URL", os.environ.get("JELLYFIN_HOST_URL", "")).rstrip("/")
    token = config.get("JELLYFIN_API_TOKEN", os.environ.get("JELLYFIN_API_TOKEN", "")).strip()
    if not base.startswith(("http://", "https://")) or not token:
        return None
    tag_names = {
        "keep": config.get("KEEP_TAG", os.environ.get("KEEP_TAG", "keep")).casefold(),
        "protected": config.get("PROTECT_TAG", os.environ.get("PROTECT_TAG", "keep-forever")).casefold(),
        "disliked": config.get("DISLIKE_TAG", os.environ.get("DISLIKE_TAG", "not-at-all")).casefold(),
        "keep_all": config.get("KEEP_ALL_SEASONS_TAG", os.environ.get("KEEP_ALL_SEASONS_TAG", "keep-all-seasons")).casefold(),
    }
    headers = _poster_headers(token)
    signals = {"Movies": {}, "TV": {}}
    users_response = requests.get(base + "/Users", headers=headers, timeout=(3, 8), allow_redirects=False)
    users_response.raise_for_status()
    users = users_response.json()
    if not isinstance(users, list) or not users:
        return None
    for user in users:
        user_id = user.get("Id")
        if not user_id:
            return None
        for library, media_type in (("Movies", "Movie"), ("TV", "Series")):
            response = requests.get(base + "/Users/" + quote(str(user_id), safe="") + "/Items",
                                    params={"Recursive": "true", "IncludeItemTypes": media_type,
                                            "Fields": "Path,Tags"},
                                    headers=headers, timeout=(3, 12), allow_redirects=False)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("Items"), list):
                return None
            for media in payload["Items"]:
                folder = _poster_folder(media, media_type)
                if not folder:
                    continue
                sig = signals[library].setdefault(folder, {"favorite": False, "keep": False,
                                                            "protected": False, "disliked": False,
                                                            "keep_all": False})
                sig["favorite"] |= bool((media.get("UserData") or {}).get("IsFavorite"))
                tags = {str(t).casefold() for t in (media.get("Tags") or [])}
                for key, tag in tag_names.items():
                    sig[key] |= tag in tags
                if sig["protected"]:
                    sig["keep_all"] = True
    return signals


def _dashboard_signals(config):
    """Cache for 60 seconds; errors show unknown rather than stale or unverified status."""
    now = time.monotonic()
    cache_key = tuple(sorted((key, config.get(key, os.environ.get(key, "")))
                              for key in ("JELLYFIN_HOST_URL", "JELLYFIN_API_TOKEN", "KEEP_TAG",
                                          "PROTECT_TAG", "DISLIKE_TAG", "KEEP_ALL_SEASONS_TAG")))
    with _SIGNAL_LOCK:
        if _SIGNAL_CACHE.get("key") == cache_key and now - _SIGNAL_CACHE.get("time", 0) < 60:
            return _SIGNAL_CACHE["value"]
    try:
        value = _live_jellyfin_signals(config)
    except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError):
        app.logger.warning("Dashboard Jellyfin signals unavailable", exc_info=True)
        value = None
    with _SIGNAL_LOCK:
        _SIGNAL_CACHE.update(key=cache_key, time=time.monotonic(), value=value)
    return value


_SIGNAL_LOCK = threading.Lock()
_SIGNAL_CACHE = {}

def filesystem_stages(state, config, *, max_entries=None):
    """Read-only lifecycle inventory. Missing mounts are reported, not counted as empty."""
    stages = {label: [] for label in ("Waiting", "Holding", "Removal", "Keep")}
    warnings = []
    media_root = config.get("MEDIA_PATH", os.environ.get("MEDIA_PATH", "/media"))
    layout = (("Movies", "RADARR", "ENABLE_MOVIES",
               {"Waiting": "Movies", "Holding": "Movies_hold",
                "Removal": "Movies_removal", "Keep": "Movies_keep"}, ""),
              ("TV", "SONARR", "ENABLE_TV",
               {"Waiting": "TV", "Holding": "TV_hold",
                "Removal": "TV_removal", "Keep": "TV_keep"}, "TV/"))
    sections = {"Waiting": "first_seen", "Holding": "queued",
                "Removal": "in_removal", "Keep": "keep_seen"}
    for library, prefix, enabled_key, defaults, key_prefix in layout:
        enabled = str(config.get(enabled_key, os.environ.get(enabled_key,
                      "true" if library == "Movies" else "false"))).lower() == "true"
        if not enabled:
            continue
        for label, dirname in defaults.items():
            kind = "TRANSIENT" if label == "Waiting" else label.upper()
            directory = os.environ.get(f"{prefix}_{kind}_PATH") or os.path.join(media_root, dirname)
            try:
                with os.scandir(directory) as entries:
                    names = []
                    for count, entry in enumerate(entries, 1):
                        if max_entries is not None and count > max_entries:
                            raise OSError('Inventory observation bound exceeded')
                        if entry.is_dir(follow_symlinks=False):
                            names.append(entry.name)
                    names.sort(key=str.casefold)
            except OSError:
                warnings.append(f"{library} {label}: directory unavailable ({directory})")
                continue
            for name in names:
                key = key_prefix + name
                stages[label].append({
                    "title": name, "library": library,
                    "since": state.get(sections[label], {}).get(key),
                })
    return stages, warnings


def collection_health(state, stages, warnings, config=None):
    """Compare readable folders and tracking records without changing either."""
    sections = {"Waiting": "first_seen", "Holding": "queued",
                "Removal": "in_removal", "Keep": "keep_seen"}
    config = config or {}
    enabled = {library for library, key, fallback in (("Movies", "ENABLE_MOVIES", "true"), ("TV", "ENABLE_TV", "false"))
               if str(config.get(key, os.environ.get(key, fallback))).lower() == "true"}
    present = {}
    for stage, items in stages.items():
        for item in items:
            if item["library"] in enabled:
                present.setdefault((item["library"], item["title"]), set()).add(stage)
    unavailable = {(library, stage)
                   for library in ("Movies", "TV") for stage in sections
                   if any(w.startswith(f"{library} {stage}:") for w in warnings)}
    issues = []
    for (library, title), locations in present.items():
        if len(locations) > 1:
            issues.append({"library": library, "title": title,
                           "detail": "Folder appears in multiple lifecycle directories: "
                                     + ", ".join(sorted(locations)) + ". Review manually; no files were moved."})
    for stage, items in stages.items():
        for item in items:
            if item["library"] not in enabled or item["since"] is not None:
                continue
            key = ("TV/" if item["library"] == "TV" else "") + item["title"]
            recorded = [label for label, section in sections.items()
                        if key in state.get(section, {})]
            if recorded:
                detail = (f"{stage}: folder has no tracking timestamp yet; "
                          f"tracking exists in {', '.join(recorded)}. "
                          "Review after the next audit; no dates were changed.")
            else:
                detail = (f"{stage}: folder has no tracking timestamp yet; "
                          "no lifecycle tracking record exists. "
                          "Manual review recommended; no dates were changed.")
            issues.append({"library": item["library"], "title": item["title"],
                           "detail": detail})
    for stage, section in sections.items():
        for key in state.get(section, {}):
            if not isinstance(key, str):
                continue
            library = "TV" if key.startswith("TV/") else "Movies"
            title = key[3:] if library == "TV" else key
            if library not in enabled or (library, stage) in unavailable:
                continue
            locations = present.get((library, title), set())
            if stage not in locations:
                if locations:
                    detail = (f"{stage} tracking record, but folder is in "
                              + ", ".join(sorted(locations)) + ". Review tracking after the next audit.")
                elif not any(lib == library for lib, _ in unavailable):
                    detail = f"{stage}: tracking record has no matching folder in readable lifecycle directories"
                else:
                    continue
                issues.append({"library": library, "title": title, "detail": detail})
    for key, entry in state.get("arr_sync_pending", {}).items():
        if not isinstance(key, str):
            continue
        library = "TV" if key.startswith("TV/") else "Movies"
        title = key[3:] if library == "TV" else key
        if library not in enabled:
            continue
        stage = entry.get("stage", "unknown") if isinstance(entry, dict) else "unknown"
        issues.append({"library": library, "title": title,
                       "detail": f"Radarr/Sonarr sync pending for {stage}"})
    return sorted(issues, key=lambda item: (item["library"], item["title"].casefold(), item["detail"]))


@app.get("/")
def dashboard(initial_workspace="Overview"):
    actions = load_actions()
    state_error = None
    try:
        state = load_state()
    except RuntimeError as exc:
        state = {}
        state_error = str(exc)
    config = load_config()
    stages, inventory_warnings = filesystem_stages(state, config)
    health_issues = collection_health(state, stages, inventory_warnings, config)
    enabled_libraries=[library for library,key,fallback in (('Movies','ENABLE_MOVIES','true'),('TV','ENABLE_TV','false'))
        if str(config.get(key,os.environ.get(key,fallback))).lower()=='true']
    clock_coverage=summarize_dashboard_clocks(state,stages,inventory_warnings,libraries=enabled_libraries,
        tracking_available=state_error is None)
    def setting_days(key, fallback):
        try:
            value=int(config.get(key, os.environ.get(key, str(fallback))))
            minimum=1 if key in ('HOLDING_DAYS','REMOVAL_DAYS') else 0
            return value if minimum <= value <= 100000 else None
        except (ValueError, TypeError):
            return None

    removal_days=setting_days('REMOVAL_DAYS',7)
    deadlines = {"Waiting": {"Movies": setting_days("MOVIE_WAIT_DAYS", 30),
                              "TV": setting_days("TV_WAIT_DAYS", 60)},
                 "Holding": {"Movies": setting_days("HOLDING_DAYS", 7),
                             "TV": setting_days("HOLDING_DAYS", 7)},
                 "Removal": {"Movies": removal_days, "TV": removal_days}}
    stage_explanations = {
        "Waiting": "Tracked in the incoming library. Playback, favorites, and protection rules can change what happens next.",
        "Holding": "In the holding period before removal. Jellyfin signals and safety rules may prevent the next move.",
        "Removal": "In the final removal stage. Deletion requires a fresh audit and must pass all deletion safeguards.",
        "Keep": "Tracked in the Keep library. TV season pruning, if enabled, has separate safeguards."
    }
    live_signals = _dashboard_signals(config)
    favorites_trigger_keep = str(config.get("FAVORITES_TRIGGER_KEEP", os.environ.get("FAVORITES_TRIGGER_KEEP", "true"))).lower() == "true"
    deletion_enabled = str(config.get("ALLOW_PERMANENT_DELETE", os.environ.get("ALLOW_PERMANENT_DELETE", "false"))).lower() == "true"
    preview = []
    for stage, items in stages.items():
        for item in items:
            item["reason"] = stage_explanations[stage]
            item.update(lifecycle_clock(item['since'],limit=deadlines.get(stage,{}).get(item['library'])))
            if stage=='Removal':item['days_left']=item['deadline_days']
            sig = live_signals.get(item["library"], {}).get(item["title"].casefold()) if live_signals is not None else None
            item["jellyfin_signals"] = sig
            limit=deadlines.get(stage,{}).get(item['library'])
            if stage!='Keep' and limit is None:
                decision,explanation='unknown','Lifecycle duration unavailable; review saved settings.'
            else:
                decision, explanation = decide(stage, item["elapsed_days"],limit or 0,sig,favorites_trigger_keep)
            if stage == "Removal" and (sig is None or sig.get("protected") or sig.get("keep") or (favorites_trigger_keep and sig.get("favorite"))):
                decision, explanation = "blocked", "Deletion blocked: Jellyfin status unknown or title protected. Manual rescue may be needed."
            if stage == "Removal" and not deletion_enabled:
                decision, explanation = "blocked", "Permanent deletion is disabled by the master safety switch."
            item["decision"] = decision
            item["decision_reason"] = explanation
            if item["due"] and decision not in ("blocked", "unknown", "keep", "rescue") and (stage != "Removal" or sig is not None):
                action = {"Waiting": "Review for move to Holding",
                          "Holding": "Review for move to Removal",
                          "Removal": "Review for permanent deletion"}.get(stage)
                if action:
                    preview.append({"title": item["title"], "library": item["library"],
                                    "stage": stage, "action": action})
    preview.sort(key=lambda item: (item["library"], item["stage"], item["title"].casefold()))
    display_zone=config.get('SQLITE_DAILY_RUN_TIMEZONE') or os.environ.get('SQLITE_DAILY_RUN_TIMEZONE') or os.environ.get('TZ')
    run = selected_run_snapshot(snapshot)
    history = selected_run_history(read_history, 100)
    return render_template("dashboard.html", scan_view=build_scan_view(run, history, timezone_name=display_zone), initial_workspace=initial_workspace, overview=dashboard_overview(stages, clock_coverage, libraries=enabled_libraries, tracking_available=state_error is None, limit=3), dashboard_timezone=display_zone, clock_coverage=clock_coverage, actions=actions, state=state, state_error=state_error, stages=stages, inventory_warnings=inventory_warnings, health_issues=health_issues, run=run, history=history,
                           preview=preview, dry_run=load_config().get("DRY_RUN", os.environ.get("DRY_RUN", "true")).lower() == "true")


@app.get("/review")
def dashboard_review():
    """Separate read-only diagnostics page using the same dashboard capture path."""
    return dashboard(initial_workspace="Review")


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


@app.template_filter('observation_datetime')
def format_observation_datetime(value,timezone_name=None):
    return observation_datetime(value,timezone_name)


@app.template_filter("friendly_date")
def friendly_date(value):
    """Show readable dates while preserving unexpected legacy values."""
    if not value:
        return "Unknown"
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%b %d, %Y")
    except (ValueError, TypeError, OverflowError):
        return str(value)


def _jellyfin_item_id(title, library):
    if not title or len(title) > 250 or library not in ("Movies", "TV"):
        return None, None
    config = load_config()
    base = config.get("JELLYFIN_HOST_URL", os.environ.get("JELLYFIN_HOST_URL", "")).rstrip("/")
    token = config.get("JELLYFIN_API_TOKEN", os.environ.get("JELLYFIN_API_TOKEN", "")).strip()
    if not base.startswith(("http://", "https://")) or not token:
        return None, None
    media_type = "Movie" if library == "Movies" else "Series"
    index = _poster_index(base, token, media_type)
    normalized = title.casefold()
    display_name = re.sub(r"\s*\(\d{4}\)\s*$", "", title).strip().casefold()
    item_id = (index.get(normalized) or index.get("name:" + normalized)
               or index.get("name:" + display_name))
    return base, item_id


@app.get("/api/jellyfin-link")
def jellyfin_link():
    """Open an existing Jellyfin item without leaking API credentials."""
    title = request.args.get("title", "").strip()
    library = request.args.get("library", "")
    if not title or len(title) > 250 or library not in ("Movies", "TV"):
        return Response(status=400)
    try:
        base, item_id = _jellyfin_item_id(title, library)
        if not item_id:
            return Response("Title not found in Jellyfin.", status=404)
        return redirect(base + "/web/index.html#!/details?id=" + quote(item_id, safe=""), code=302)
    except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError):
        app.logger.warning("Jellyfin link lookup failed for %s", library, exc_info=True)
        return Response("Unable to find title in Jellyfin.", status=404)


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
        display_name = re.sub(r"\s*\(\d{4}\)\s*$", "", title).strip().casefold()
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


@app.get("/settings/export-safe")
def export_safe_settings():
    """Download only allowlisted non-secret settings; never expose raw configuration."""
    if not getattr(g, "user", None) or not g.user["admin"]:
        return Response("Administrator access required.", 403)
    response = Response(json.dumps({
        "note": "Shareable settings snapshot; credentials, URLs and filesystem paths excluded.",
        "settings": redacted_config(load_config()),
    }, indent=2), mimetype="application/json")
    response.headers["Content-Disposition"] = 'attachment; filename="auditor_settings_safe.json"'
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/logs/diagnostics")
def export_diagnostics():
    """Download a bounded, read-only diagnostic ZIP without tokens or configuration secrets."""
    if not getattr(g, "user", None) or not g.user["admin"]:
        return Response("Administrator access required.", 403)

    # Deliberately exclude raw settings, state, cookies, and container environment.
    # Folder names in activity logs can still be personal; share the ZIP selectively.
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "log_format": "JSON Lines (one action per line)",
        "included": ["recent activity log", "non-secret safety configuration"],
        "excluded": ["API keys", "passwords", "tokens", "state file", "environment variables"],
    }
    config = load_config()
    safe_keys = ("DRY_RUN", "ALLOW_PERMANENT_DELETE", "ALLOW_FILESYSTEM_DELETE",
                 "ENABLE_SEASON_PRUNING", "MAX_ACTIONS_PER_RUN", "ENABLE_MOVIES", "ENABLE_TV")
    report["safety_settings"] = {
        key: config.get(key, os.environ.get(key, DEFAULTS.get(key, "unset")))
        for key in safe_keys
    }
    try:
        # Only export the last 2 MiB of activity to avoid excessive memory use.
        path = Path(ACTION_LOG_FILE)
        raw = b""
        if path.is_file():
            with path.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                length = handle.tell()
                handle.seek(max(0, length - 2 * 1024 * 1024))
                raw = handle.read()
            if length > 2 * 1024 * 1024:
                raw = raw.partition(b"\\n")[2]  # omit truncated first record
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("diagnostics.json", json.dumps(report, indent=2))
            archive.writestr("recent_actions.jsonl", raw)
        buffer.seek(0)
        return send_file(buffer, mimetype="application/zip", as_attachment=True,
                         download_name="auditor_diagnostics.zip", max_age=0)
    except OSError:
        return Response("Diagnostic export unavailable.", 503)


@app.get("/logs/export")
def export_logs():
    """Download persisted structured activity only; never expose arbitrary server paths."""
    if not getattr(g, "user", None) or not g.user["admin"]:
        return Response("Administrator access required.", 403)
    path = Path(ACTION_LOG_FILE)
    try:
        if not path.is_file():
            return Response("No persisted action log available.", 404)
        return send_file(path, mimetype="application/x-ndjson", as_attachment=True,
                         download_name="auditor_actions.jsonl", max_age=0)
    except OSError:
        return Response("Action log unavailable.", 503)


@app.get("/logs")
def logs():
    return render_template("logs.html", actions=load_actions(1000))


def admin_authorized():
    return bool(getattr(g, "user", None) and g.user["admin"])


# Experimental SQLite recovery views are opt-in and never select SQLite as
# the production tracking backend. Only the literal value "true" enables them.
if (not read_only_service_enabled()
        and os.environ.get("EXPERIMENTAL_SQLITE_RECOVERY_VIEW", "").lower() == "true"):
    from app.sqlite_recovery_api import create_recovery_status_blueprint
    from app.sqlite_recovery_view import create_recovery_view_blueprint

    _experimental_database = os.environ.get("EXPERIMENTAL_SQLITE_RECOVERY_DB", "")
    if not _experimental_database:
        raise RuntimeError("Experimental SQLite recovery database path required")
    app.register_blueprint(create_recovery_status_blueprint(
        _experimental_database, is_admin=admin_authorized,
    ))
    app.register_blueprint(create_recovery_view_blueprint(
        _experimental_database, is_admin=admin_authorized,
    ))


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if not admin_authorized():
        return Response("Settings require WEB_ADMIN_PASSWORD (and HTTP Basic authentication).",
                        401, {"WWW-Authenticate": 'Basic realm="Auditor settings"'})
    preview_mode = _preview_backend_gate().preview_release_enabled()
    live_mode = _preview_backend_gate().live_release_enabled()
    bound_mode=preview_mode or live_mode
    locked_settings=()
    if live_mode:
        from app.sqlite_live_settings import LOCKED
        locked_settings=LOCKED
    saved = load_config()
    pending_settings = {'status':'none','changed_keys':[]}
    settings_application = {'status':'none'}
    if bound_mode:
        from app.sqlite_preview_settings import pending_request_summary
        from config_store import CONFIG_FILE, initial_environment
        from app.sqlite_preview_settings_apply import application_status
        baseline = initial_environment()
        pending_settings = pending_request_summary(config_path=CONFIG_FILE,environment=baseline)
        settings_application = application_status(settings=baseline)
    error = None
    success = request.args.get("saved") == "1"
    requested = request.args.get("requested") == "1"
    unchanged = request.args.get("unchanged") == "1"
    if request.method == "POST":
        # Reject cross-origin browser submissions; don't accept unauthenticated writes.
        origin = request.headers.get("Origin") or request.headers.get("Referer")
        if not origin or urlsplit(origin).netloc != request.host:
            return Response("Invalid request origin", 403)
        if bound_mode and settings_application['status']=='recovery_required':
            return redirect(url_for('settings',apply_error='1'))
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
            if not bound_mode and (updated.get("DRY_RUN", os.environ.get("DRY_RUN", "true")).lower() == "false"
                    or updated.get("ALLOW_PERMANENT_DELETE", "false") == "true"
                    or updated.get("ALLOW_FILESYSTEM_DELETE", "false") == "true"
                    or updated.get("ALLOW_CROSS_FILESYSTEM_MOVES", "false") == "true"
                    or updated.get("ENABLE_SEASON_PRUNING", "false") == "true"):
                if request.form.get("safety_confirmation") != "I UNDERSTAND":
                    raise ValueError("Type I UNDERSTAND to confirm potentially destructive settings.")
            if bound_mode:
                if live_mode:
                    from app.sqlite_live_settings import request_settings
                else:
                    from app.sqlite_preview_settings import request_settings
                from config_store import CONFIG_FILE
                apply_now = request.form.get('settings_action') == 'apply'
                result = request_settings(config_path=CONFIG_FILE, updated=updated, environment=baseline,
                                          include_digest=apply_now)
                if apply_now:
                    # Pin the exact request just staged by this submission. If
                    # unchanged, only an explicitly supplied retained digest may
                    # select the previously reviewed request. Never adopt a newer
                    # request by rereading its digest after staging.
                    digest = result.get('request_sha256') if result['status'] == 'requested' else request.form.get('request_sha256')
                    if digest:
                        return _change_preview_settings(restore=False, request_sha256=digest)
                return redirect(url_for('settings', **{result['status']: '1'}))
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
                           success=success, preview_mode=bound_mode, live_mode=live_mode, requested=requested, unchanged=unchanged,
                           pending_settings=pending_settings, settings_application=settings_application,
                           locked_settings=locked_settings,
                           settings_applied=request.args.get('applied')=='1',
                           settings_restored=request.args.get('restored')=='1',
                           settings_apply_error=request.args.get('apply_error')=='1',
                           settings_apply_busy=request.args.get('apply_busy')=='1')


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


def _change_preview_settings(*, restore, request_sha256=None):
    if not admin_authorized():
        return Response('Administrator access required.',403)
    origin = request.headers.get('Origin') or request.headers.get('Referer')
    if not origin or urlsplit(origin).netloc != request.host:
        return Response('Invalid request origin.',403)
    gate=_preview_backend_gate()
    if not (gate.preview_release_enabled() or gate.live_release_enabled()):
        return Response('Bound settings application unavailable.',409)
    from config_store import initial_environment
    from app.sqlite_lock import StateLockBusy
    if gate.live_release_enabled():
        from app.sqlite_live_settings import apply_requested_settings,restore_previous_settings
    else:
        from app.sqlite_preview_settings_apply import apply_requested_settings, restore_previous_settings
    notification_settings = {**initial_environment(), **load_config()}
    try:
        action = restore_previous_settings if restore else apply_requested_settings
        digest = request.form.get('request_sha256','') if request_sha256 is None else request_sha256
        action(settings=initial_environment(),request_sha256=digest)
    except StateLockBusy:
        return redirect(url_for('settings',apply_busy='1'))
    except Exception:
        # Pending files and journals retain details privately; no raw errors or
        # connection credentials are returned through the settings page.
        try:
            from app.operational_notifications import NOTIFICATIONS
            NOTIFICATIONS.emit(notification_settings, 'settings_review_required')
        except Exception:
            pass  # Alerts cannot change the settings transaction's outcome.
        return redirect(url_for('settings',apply_error='1'))
    from app.operational_notifications import NOTIFICATIONS
    NOTIFICATIONS.clear('settings_review_required')
    from run_control import wake_worker
    wake_worker()  # Reload effective settings; this does not queue a scan.
    return redirect(url_for('settings',**{('restored' if restore else 'applied'):'1'}))


@app.post('/settings/apply')
def apply_preview_settings():
    return _change_preview_settings(restore=False)


@app.post('/settings/restore')
def restore_preview_settings():
    return _change_preview_settings(restore=True)


@app.post("/api/run-now")
def run_now():
    if not admin_authorized():
        return {"ok": False, "message": "Authentication required."}, 401
    origin = request.headers.get("Origin") or request.headers.get("Referer")
    if not origin or urlsplit(origin).netloc != request.host:
        return {"ok": False, "message": "Invalid request origin."}, 403
    backend = os.environ.get('AUDITOR_STATE_BACKEND', 'json')
    gate = _preview_backend_gate()
    if gate.live_release_enabled():
        data=request.get_json(silent=True)
        if not isinstance(data,dict) or set(data)!={'consume_daily_slot'} or data['consume_daily_slot'] is not True:
            return {'ok':False,'message':'Explicitly confirm using today’s live scan and action budget.'},409
        try:
            from datetime import timezone
            from app.sqlite_scheduled_production import _daily_claim_exists
            values=gate.require_sqlite_production_activation()
            if _daily_claim_exists(values,datetime.now(timezone.utc)):
                return {'ok':False,'message':'Today’s daily attempt is already claimed. No extra scan or move was queued.'},409
        except Exception:
            return {'ok':False,'message':'Live configuration needs review; no scan was queued.'},409
        from app.sqlite_scheduled_observations import COORDINATOR
        if COORDINATOR.request_manual_live():
            from run_control import wake_worker
            wake_worker()
            return {'ok':True,'message':'Live daily scan queued. It uses today’s one-action budget; no additional scheduled attempt is allowed today.'},202
        return {'ok':False,'message':'A scan is already running or queued.'},409
    if gate.preview_release_enabled() or backend == 'sqlite':
        if not gate.preview_release_enabled():
            return {'ok': False, 'message': 'This backend runs only at its configured daily time.'}, 409
        try:
            gate.require_sqlite_production_activation()
        except RuntimeError:
            return {'ok': False, 'message': 'Preview configuration unavailable; scan was not queued.'}, 409
        from app.sqlite_scheduled_observations import COORDINATOR
        if COORDINATOR.request_manual_preview():
            from run_control import wake_worker
            wake_worker()
            return {'ok': True, 'message': 'Read-only preview queued. Daily schedule unchanged.'}, 202
        return {'ok': False, 'message': 'A scan is already running or queued.'}, 409
    if backend != 'json':
        return {'ok': False, 'message': 'Unsupported run backend.'}, 409
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
