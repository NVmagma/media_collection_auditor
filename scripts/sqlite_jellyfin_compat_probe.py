#!/usr/bin/env python3
"""Read-only Jellyfin API response-shape probe.

Requires JELLYFIN_HOST_URL and JELLYFIN_API_TOKEN environment variables.
Only aggregate boolean compatibility findings are printed; no IDs, paths,
titles, tokens, raw responses or per-user details are logged.
"""

from __future__ import annotations

import json
import os
import sys
from urllib.parse import urlparse

import requests


def probe(fetch):
    """Inspect first page per user for schema compatibility, not completeness."""
    summary = {
        "users_response_list": False,
        "users_have_ids": False,
        "items_response_shape": True,
        "pagination_metadata_present": True,
        "item_id_present": True,
        "item_path_present": True,
        "item_tags_list": True,
        "user_data_present": True,
        "favorite_boolean": True,
        "played_boolean": True,
        "play_count_integer": True,
        "sampled_items": 0,
        "sampled_user_requests": 0,
        "scan_complete": False,
        "production_authorized": False,
    }
    try:
        users = fetch("/Users", None)
        if not isinstance(users, list) or not users:
            return summary
        summary["users_response_list"] = True
        ids = [u.get("Id") for u in users if isinstance(u, dict)]
        if (len(ids) != len(users) or any(not isinstance(i, str) or not i for i in ids)
                or len(ids) != len(set(ids))):
            return summary
        summary["users_have_ids"] = True
        for uid in ids:
            for kind in ("Movie", "Series"):
                data = fetch(f"/Users/{uid}/Items", {
                    "Recursive": "true", "IncludeItemTypes": kind,
                    "Fields": "Path,Tags", "StartIndex": 0, "Limit": 10,
                })
                summary["sampled_user_requests"] += 1
                if not isinstance(data, dict) or not isinstance(data.get("Items"), list):
                    summary["items_response_shape"] = False
                    return summary
                if type(data.get("TotalRecordCount")) is not int:
                    summary["pagination_metadata_present"] = False
                for item in data["Items"]:
                    summary["sampled_items"] += 1
                    if not isinstance(item, dict):
                        for field in ("item_id_present", "item_path_present",
                                      "item_tags_list", "user_data_present"):
                            summary[field] = False
                        continue
                    summary["item_id_present"] &= isinstance(item.get("Id"), str)
                    summary["item_path_present"] &= isinstance(item.get("Path"), str)
                    summary["item_tags_list"] &= isinstance(item.get("Tags"), list)
                    ud = item.get("UserData")
                    summary["user_data_present"] &= isinstance(ud, dict)
                    if not isinstance(ud, dict):
                        summary["favorite_boolean"] = False
                        summary["played_boolean"] = False
                        summary["play_count_integer"] = False
                    else:
                        summary["favorite_boolean"] &= type(ud.get("IsFavorite")) is bool
                        summary["played_boolean"] &= type(ud.get("Played")) is bool
                        summary["play_count_integer"] &= type(ud.get("PlayCount")) is int
    except (requests.RequestException, ValueError, TypeError):
        summary["request_failed"] = True
    return summary


def main():
    url = os.environ.get("JELLYFIN_HOST_URL", "").rstrip("/")
    token = os.environ.get("JELLYFIN_API_TOKEN", "").strip().strip("'\"")
    parsed = urlparse(url)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username or parsed.password or not token):
        print("Jellyfin host and token must be supplied through environment variables.", file=sys.stderr)
        return 2
    session = requests.Session()
    session.headers.update({"X-Emby-Token": token})

    def fetch(path, params):
        response = session.get(url + path, params=params, timeout=15)
        response.raise_for_status()
        return response.json()

    result = probe(fetch)
    print(json.dumps(result, sort_keys=True, indent=2))
    return 1 if result.get("request_failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
