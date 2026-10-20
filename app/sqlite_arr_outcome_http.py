"""Authenticated GET-only adapter for isolated pending Arr readback."""
from datetime import datetime, timezone
from urllib.parse import urlsplit

import requests

from app.sqlite_isolated_arr_inspection import inspect_isolated_arr_outcome


def _base_url(value):
    if not isinstance(value, str):
        raise RuntimeError("Arr readback service URL invalid")
    try:
        parts = urlsplit(value)
        _ = parts.port  # Validate malformed/non-numeric ports before any request.
    except ValueError:
        raise RuntimeError("Arr readback service URL invalid") from None
    if (parts.scheme not in ("http", "https") or not parts.hostname
            or parts.username is not None or parts.password is not None
            or parts.query or parts.fragment or any(ord(c) < 33 for c in value)
            or chr(92) in value or any(p in (".", "..") for p in parts.path.split("/"))):
        raise RuntimeError("Arr readback service URL invalid")
    return value.rstrip("/")


def inspect_isolated_arr_http(*, root, radarr_url="", radarr_key="",
                              sonarr_url="", sonarr_key="", http=None):
    """No environment credential loading, proxies, redirects, writes or retry.

    The injected HTTP transport is trusted; the default owns a fresh Session.
    Pending local identity is validated before fetch selects a service endpoint.
    """
    owned = http is None
    client = requests.Session() if owned else http
    if owned:
        client.trust_env = False
    services = {"radarr": (radarr_url, radarr_key, "movie"),
                "sonarr": (sonarr_url, sonarr_key, "series")}
    try:
        def fetch(service, title_id):
            if service not in services or type(title_id) is not int or title_id <= 0:
                raise RuntimeError("Arr readback identity invalid")
            base, key, resource = services[service]
            base = _base_url(base)
            if not isinstance(key, str) or not key.strip():
                raise RuntimeError("Arr readback credentials unavailable")
            try:
                response = client.get(base + f"/api/v3/{resource}/{title_id}",
                                      headers={"X-Api-Key": key}, timeout=15, allow_redirects=False)
                if type(response.status_code) is not int or not 200 <= response.status_code < 300:
                    raise RuntimeError("Arr readback HTTP response unavailable")
                data = response.json()
            except (requests.RequestException, ValueError, TypeError):
                raise RuntimeError("Arr readback service unavailable") from None
            if not isinstance(data, dict) or type(data.get("id")) is not int or data["id"] != title_id:
                raise RuntimeError("Arr readback response identity invalid")
            return {"service": service, "title_id": str(title_id),
                    "observed_at": datetime.now(timezone.utc), "data": data}
        return inspect_isolated_arr_outcome(root=root, fetch=fetch)
    finally:
        if owned:
            client.close()
