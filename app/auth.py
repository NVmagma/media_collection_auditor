"""Jellyfin login and durable Flask session signing key."""
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

def jellyfin_login(username, password):
    base = jellyfin_base()
    if not base or not username or not password:
        return None
    headers = {"Authorization": 'MediaBrowser Client="Media Collection Auditor", Device="Web", DeviceId="media-collection-auditor-web", Version="1.0"'}
    try:
        response = requests.post(base + "/Users/AuthenticateByName",
                                 json={"Username": username, "Pw": password},
                                 headers=headers, timeout=(3, 8), allow_redirects=False)
        if response.status_code != 200:
            return None
        data = response.json()
        user = data.get("User") or {}
        if not data.get("AccessToken") or not user.get("Id"):
            return None
        return {"name": user.get("Name", username), "id": user["Id"],
                "token": data["AccessToken"]}
    except (requests.RequestException, ValueError, TypeError, KeyError):
        return None

def current_user():
    if session.get("provider") == "local":
        return {"name": "Local administrator", "admin": True}
    if session.get("provider") != "jellyfin":
        return None
    with _TOKEN_LOCK:
        token, user_id = _TOKENS.get(session.get("jf_handle"), (None, None))
    if not token or not user_id:
        return None
    try:
        response = requests.get(jellyfin_base() + "/Users/" + user_id,
                                headers={"X-Emby-Token": token},
                                timeout=(3, 6), allow_redirects=False)
        if response.status_code != 200:
            return None
        user = response.json()
        if user.get("Id") != user_id or user.get("Policy", {}).get("IsDisabled", False):
            return None
        return {"name": user.get("Name", "Jellyfin user"),
                "admin": bool(user.get("Policy", {}).get("IsAdministrator", False))}
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        return None
