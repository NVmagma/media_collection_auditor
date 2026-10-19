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

    def jellyfin_fetch_identity(self, item_id: str) -> dict[str, Any]:
        """Read one Jellyfin item identity; does not establish protection scope."""
        item_id = _identity(item_id)
        data = _get_json(
            self.http,
            _endpoint(self.jellyfin_url, f"/Users/{self.jellyfin_user_id}/Items/{item_id}"),
            headers={"X-Emby-Token": self.jellyfin_token},
        )
        if data.get("Id") != item_id:
            raise RuntimeError("Recovery Jellyfin identity mismatch")
        return {"service": "jellyfin", "title_id": item_id,
                "observed_at": datetime.now(timezone.utc), "data": data}

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

    def jellyfin_fetch_all_users(self, item_id: str, *, season_ids: tuple[str, ...] = ()) -> dict[str, Any]:
        """Aggregate explicit user/title/season observations without assuming coverage.

        A caller must supply the complete season identity set independently.
        This method cannot establish that the set is exhaustive, so complete
        stays False until trusted library enumeration is implemented.
        """
        item_id = _identity(item_id)
        if not isinstance(season_ids, tuple) or any(
            not isinstance(value, str) or not value or value == item_id
            for value in season_ids
        ) or len(set(season_ids)) != len(season_ids):
            raise RuntimeError("Recovery season identity set invalid")
        season_ids = tuple(_identity(value) for value in season_ids)
        users_url = _endpoint(self.jellyfin_url, "/Users")
        try:
            response = self.http.get(
                users_url, headers={"X-Emby-Token": self.jellyfin_token}, timeout=15
            )
            response.raise_for_status()
            users = response.json()
        except (requests.RequestException, ValueError, TypeError) as exc:
            raise RuntimeError("Recovery Jellyfin user enumeration failed") from exc
        if not isinstance(users, list) or not users:
            raise RuntimeError("Recovery Jellyfin users unavailable")
        ids = []
        for user in users:
            if not isinstance(user, dict):
                raise RuntimeError("Recovery Jellyfin user identity invalid")
            ids.append(_identity(user.get("Id")))
        if len(set(ids)) != len(ids):
            raise RuntimeError("Recovery Jellyfin duplicate user identity")
        flags = {"keep": False, "keep_forever": False,
                 "keep_all_seasons": False, "favorite": False}
        for user_id in ids:
            for title_id in (item_id, *season_ids):
                data = _get_json(
                    self.http,
                    _endpoint(self.jellyfin_url, f"/Users/{user_id}/Items/{title_id}"),
                    headers={"X-Emby-Token": self.jellyfin_token},
                )
                if data.get("Id") != title_id:
                    raise RuntimeError("Recovery Jellyfin identity mismatch")
                tags, user_data = data.get("Tags"), data.get("UserData")
                if not isinstance(tags, list) or not all(
                    isinstance(tag, str) for tag in tags
                ):
                    raise RuntimeError("Recovery Jellyfin tags unavailable")
                if not isinstance(user_data, dict) or type(user_data.get("IsFavorite")) is not bool:
                    raise RuntimeError("Recovery Jellyfin favorite unavailable")
                tags = {tag.casefold() for tag in tags}
                for flag in ("keep", "keep_forever", "keep_all_seasons"):
                    flags[flag] |= flag.replace("_", "-") in tags
                flags["favorite"] |= user_data["IsFavorite"]
        return {
            "service": "jellyfin", "title_id": item_id,
            "observed_at": datetime.now(timezone.utc),
            "data": {"available": True, "complete": False, **flags},
            "user_ids": tuple(ids),
        }

    def jellyfin_fetch_verified_series(self, series_id: str) -> dict[str, Any]:
        """Enumerate Jellyfin seasons and users; fail closed on partial pages.

        The server's season list is independently obtained rather than trusted
        from the pending operation. Even a complete response is diagnostic only.
        """
        series_id = _identity(series_id)
        url = _endpoint(
            self.jellyfin_url,
            f"/Shows/{series_id}/Seasons?UserId={self.jellyfin_user_id}&StartIndex=0&Limit=10000",
        )
        response = _get_json(
            self.http, url, headers={"X-Emby-Token": self.jellyfin_token},
        )
        items, total = response.get("Items"), response.get("TotalRecordCount")
        if not isinstance(items, list) or type(total) is not int or total < 0:
            raise RuntimeError("Recovery Jellyfin season enumeration incomplete")
        if len(items) != total or len(items) > 10000:
            raise RuntimeError("Recovery Jellyfin season enumeration incomplete")
        ids = []
        for season in items:
            if not isinstance(season, dict) or season.get("SeriesId") != series_id:
                raise RuntimeError("Recovery Jellyfin season ownership mismatch")
            ids.append(_identity(season.get("Id")))
        if len(set(ids)) != len(ids) or series_id in ids:
            raise RuntimeError("Recovery Jellyfin season identities ambiguous")
        observation = self.jellyfin_fetch_all_users(
            series_id, season_ids=tuple(ids)
        )
        # Multi-user enumeration and per-season reads succeeded, but the
        # API does not supply a transactional snapshot of library membership.
        # A season added during enumeration must not be silently missed.
        confirm = _get_json(
            self.http, url, headers={"X-Emby-Token": self.jellyfin_token},
        )
        confirm_items = confirm.get("Items")
        if (type(confirm.get("TotalRecordCount")) is not int
                or confirm["TotalRecordCount"] != total
                or not isinstance(confirm_items, list)
                or len(confirm_items) != total
                or any(not isinstance(item, dict)
                       or not isinstance(item.get("Id"), str)
                       or item.get("SeriesId") != series_id
                       for item in confirm_items)
                or {item["Id"] for item in confirm_items} != set(ids)):
            raise RuntimeError("Recovery Jellyfin season set changed during inspection")
        # Re-enumerate users as well: a new user appearing during the read
        # could carry protection information that was not inspected.
        try:
            users_response = self.http.get(
                _endpoint(self.jellyfin_url, "/Users"),
                headers={"X-Emby-Token": self.jellyfin_token}, timeout=15,
            )
            users_response.raise_for_status()
            confirmed_users = users_response.json()
        except (requests.RequestException, ValueError, TypeError) as exc:
            raise RuntimeError("Recovery Jellyfin user recheck failed") from exc
        if not isinstance(confirmed_users, list) or len(confirmed_users) == 0:
            raise RuntimeError("Recovery Jellyfin user set changed during inspection")
        try:
            confirmed_ids = [_identity(user.get("Id")) for user in confirmed_users]
        except (AttributeError, RuntimeError) as exc:
            raise RuntimeError("Recovery Jellyfin user recheck invalid") from exc
        if len(set(confirmed_ids)) != len(confirmed_ids):
            raise RuntimeError("Recovery Jellyfin duplicate user identity")
        # The original user list is retained in the diagnostic result so a
        # caller can compare the same scope, without treating it as authority.
        if set(confirmed_ids) != set(observation["user_ids"]):
            raise RuntimeError("Recovery Jellyfin user set changed during inspection")
        observation.pop("user_ids")
        # Non-atomic observations remain unsuitable for automatic clearance.
        return observation

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
