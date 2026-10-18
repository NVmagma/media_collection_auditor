"""Experimental authenticated, read-only HTTP adapters for recovery inspection.

Never imports production audit runtime, performs mutations, or clears intents.
The Jellyfin adapter requires a specific user ID to inspect favorites; a
single-user response must not be mistaken for complete multi-user coverage.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests


def _get_json(http: Any, url: str, *, headers: dict[str, str]) -> dict[str, Any]:
    try:
        response = http.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError, TypeError) as exc:
        raise RuntimeError("Recovery service read failed") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Recovery service returned invalid data")
    return data


def _endpoint(base: str, path: str) -> str:
    if not isinstance(base, str) or not base.startswith(("https://", "http://")):
        raise RuntimeError("Recovery service URL invalid")
    if not base.rstrip("/") or not path.startswith("/"):
        raise RuntimeError("Recovery service endpoint invalid")
    return base.rstrip("/") + path


def _identity(value: str) -> str:
    if not isinstance(value, str) or not value or not all(
        char.isalnum() or char in "-_" for char in value
    ):
        raise RuntimeError("Recovery item identity invalid")
    return value


class ReadOnlyRecoveryHTTP:
    """Explicit credentials and service endpoints; no environment side effects."""

    def __init__(
        self, *, jellyfin_url: str, jellyfin_token: str,
        jellyfin_user_id: str, radarr_url: str = "", radarr_key: str = "",
        sonarr_url: str = "", sonarr_key: str = "", http: Any = requests,
    ):
        if not isinstance(jellyfin_token, str) or not jellyfin_token:
            raise RuntimeError("Recovery Jellyfin credentials unavailable")
        self.jellyfin_url = jellyfin_url
        self.jellyfin_token = jellyfin_token
        self.jellyfin_user_id = _identity(jellyfin_user_id)
        self.arr = {"radarr": (radarr_url, radarr_key, "movie"),
                    "sonarr": (sonarr_url, sonarr_key, "series")}
        self.http = http

    def jellyfin_fetch(self, item_id: str) -> dict[str, Any]:
        """Fetch title tags and one user's favorite; incomplete scope blocks clearance."""
        item_id = _identity(item_id)
        data = _get_json(
            self.http, _endpoint(self.jellyfin_url, f"/Users/{self.jellyfin_user_id}/Items/{item_id}"),
            headers={"X-Emby-Token": self.jellyfin_token},
        )
        if data.get("Id") != item_id:
            raise RuntimeError("Recovery Jellyfin identity mismatch")
        tags = data.get("Tags")
        user_data = data.get("UserData")
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise RuntimeError("Recovery Jellyfin tags unavailable")
        if not isinstance(user_data, dict) or type(user_data.get("IsFavorite")) is not bool:
            raise RuntimeError("Recovery Jellyfin favorite unavailable")
        lowered = {tag.casefold() for tag in tags}
        protection = {
            "available": True,
            # One user is insufficient to prove no other user's favorites.
            # Explicitly incomplete until multi-user/season verification exists.
            "complete": False,
            "keep": "keep" in lowered,
            "keep_forever": "keep-forever" in lowered,
            "keep_all_seasons": "keep-all-seasons" in lowered,
            "favorite": user_data["IsFavorite"],
        }
        return {
            "service": "jellyfin", "title_id": item_id,
            "observed_at": datetime.now(timezone.utc), "data": protection,
        }

    def arr_fetch(self, service: str, title_id: int) -> dict[str, Any]:
        """Read exact title record from Radarr or Sonarr; never mutate it."""
        if service not in self.arr or type(title_id) is not int or title_id <= 0:
            raise RuntimeError("Recovery Arr identity invalid")
        url, key, resource = self.arr[service]
        if not isinstance(key, str) or not key:
            raise RuntimeError("Recovery Arr credentials unavailable")
        record = _get_json(
            self.http, _endpoint(url, f"/api/v3/{resource}/{title_id}"),
            headers={"X-Api-Key": key},
        )
        if type(record.get("id")) is not int or record["id"] != title_id:
            raise RuntimeError("Recovery Arr response identity mismatch")
        return {
            "service": service, "title_id": str(title_id),
            "observed_at": datetime.now(timezone.utc), "data": record,
        }
