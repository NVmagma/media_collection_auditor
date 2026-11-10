"""Handle Jellyfin login and keep the Flask signing key across restarts."""
import os
import secrets
import threading
from pathlib import Path
import requests
from flask import session
from config_store import load_config

_TOKENS = {}
_TOKEN_LOCK = threading.Lock()


def store_token(token, user_id):
    handle = secrets.token_urlsafe(32)
    with _TOKEN_LOCK:
        _TOKENS[handle] = (token, user_id)
    return handle


def discard_token(handle):
    with _TOKEN_LOCK:
        _TOKENS.pop(handle, None)


KEY_FILE = Path(os.environ.get("WEB_SESSION_KEY_FILE", "/app/logs/web_session.key"))

def session_key():
    configured = os.environ.get("WEB_SESSION_SECRET", "")
    if configured:
        return configured
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        return KEY_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        try:
            with KEY_FILE.open("x", encoding="utf-8") as handle:
                os.chmod(KEY_FILE, 0o600)
                key = secrets.token_hex(32)
                handle.write(key)
                return key
        except FileExistsError:
            return KEY_FILE.read_text(encoding="utf-8").strip()

def jellyfin_base():
    config = load_config()
    return config.get("JELLYFIN_HOST_URL", os.environ.get("JELLYFIN_HOST_URL", "")).rstrip("/")

def jellyfin_headers(token=None):
    auth = 'MediaBrowser Client="Media Collection Auditor", Device="Media Auditor Web", DeviceId="media-auditor-web", Version="1.0"'
    if token:
        auth += ', Token="' + token + '"'
    headers = {"X-Emby-Authorization": auth, "Authorization": auth}
    if token:
        headers["X-Emby-Token"] = token
    return headers


def jellyfin_login(username, password):
    base = jellyfin_base()
    if not base:
        return None, "Jellyfin server URL is not configured."
    if not username or not password:
        return None, "Enter a username and password."
    try:
        response = requests.post(base + "/Users/AuthenticateByName",
                                 json={"Username": username, "Pw": password},
                                 headers=jellyfin_headers(), timeout=(3, 10),
                                 allow_redirects=False)
        if response.status_code in (401, 403):
            return None, "Jellyfin rejected those credentials."
        if response.status_code != 200:
            return None, "Jellyfin authentication returned HTTP " + str(response.status_code) + "."
        data = response.json()
        user = data.get("User") or {}
        if not data.get("AccessToken") or not user.get("Id"):
            return None, "Jellyfin did not return a usable login session."
        if user.get("Policy", {}).get("IsDisabled"):
            return None, "This Jellyfin account is disabled."
        return {"name": user.get("Name", username), "id": user["Id"],
                "token": data["AccessToken"]}, None
    except requests.exceptions.Timeout:
        return None, "Jellyfin timed out. Check the configured address."
    except requests.exceptions.RequestException:
        return None, "Unable to connect to Jellyfin from this container."
    except (ValueError, TypeError, AttributeError):
        return None, "Jellyfin returned an unexpected authentication response."


def verify_user(token, user_id):
    try:
        response = requests.get(jellyfin_base() + "/Users/Me",
                                headers=jellyfin_headers(token),
                                timeout=(3, 7), allow_redirects=False)
        if response.status_code != 200:
            return None
        user = response.json()
        if user.get("Id") != user_id or user.get("Policy", {}).get("IsDisabled"):
            return None
        return {"name": user.get("Name", "Jellyfin user"),
                "admin": bool(user.get("Policy", {}).get("IsAdministrator", False))}
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        return None


def current_user():
    if session.get("provider") == "local":
        from app.unraid_setup import account_version
        if session.get('account_version') != account_version(): return None
        return {"name": "Local administrator", "admin": True}
    if session.get("provider") != "jellyfin":
        return None
    with _TOKEN_LOCK:
        token, user_id = _TOKENS.get(session.get("jf_handle"), (None, None))
    if not token or not user_id:
        return None
    return verify_user(token, user_id)
