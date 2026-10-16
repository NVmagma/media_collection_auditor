"""Read-only connectivity checks for configured media services."""
import os
from urllib.parse import urlsplit
import requests
from config_store import load_config

SERVICES = {
    "jellyfin": ("JELLYFIN_HOST_URL", "JELLYFIN_API_TOKEN", "/System/Info", "X-Emby-Token"),
    "radarr": ("RADARR_URL", "RADARR_API_KEY", "/api/v3/system/status", "X-Api-Key"),
    "sonarr": ("SONARR_URL", "SONARR_API_KEY", "/api/v3/system/status", "X-Api-Key"),
}

def check_connection(service):
    if service not in SERVICES:
        return {"ok": False, "message": "Unknown service."}, 400
    url_key, token_key, endpoint, header = SERVICES[service]
    saved = load_config()
    base = saved.get(url_key, os.environ.get(url_key, "")).strip().rstrip("/")
    token = saved.get(token_key, os.environ.get(token_key, "")).strip()
    if not base or not token:
        return {"ok": False, "message": "Configure the service URL and API key, then save settings."}, 400
    parts = urlsplit(base)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password or parts.path not in ("", "/") or parts.query or parts.fragment:
        return {"ok": False, "message": "Invalid service URL. Use a base URL such as http://host:8096."}, 400
    try:
        response = requests.get(base + endpoint, headers={header: token}, timeout=(3, 7), allow_redirects=False)
        if response.status_code == 401 or response.status_code == 403:
            return {"ok": False, "message": "Authentication failed. Check the API key."}, 200
        if 300 <= response.status_code < 400:
            return {"ok": False, "message": "The server redirected the request. Check its URL."}, 200
        if not response.ok:
            return {"ok": False, "message": f"Server returned HTTP {response.status_code}."}, 200
        try:
            info = response.json()
        except ValueError:
            return {"ok": False, "message": "Server did not return valid JSON."}, 200
        if not isinstance(info, dict):
            return {"ok": False, "message": "Unexpected server response."}, 200
        return {"ok": True, "message": f"Connected to {service.capitalize()} successfully."}, 200
    except requests.exceptions.Timeout:
        return {"ok": False, "message": "Connection timed out. Check the address and network."}, 200
    except requests.exceptions.RequestException:
        return {"ok": False, "message": "Connection failed. Check the address, port, and TLS settings."}, 200
