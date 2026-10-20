#!/usr/bin/env python3
"""Read-only full Jellyfin response contract scan. No identifying output."""
from __future__ import annotations

import json
import os
import sys
from urllib.parse import urlparse

import requests

PAGE_SIZE = 100
MAX_ITEMS_PER_USER_KIND = 100000


def scan(fetch):
    report = {
        "scan_complete": False, "production_authorized": False,
        "read_only": True, "users_checked": 0, "pages_checked": 0,
        "items_checked": 0, "movie_items_checked": 0,
        "series_items_checked": 0, "failure_stage": None,
        "failure_category": None,
    }
    stage = "users"
    requested_kind = None
    returned_kind = None
    validation_failure = None
    try:
        users = fetch("/Users", None)
        if not isinstance(users, list) or not users:
            raise ValueError("users_shape")
        ids = [u.get("Id") for u in users if isinstance(u, dict)]
        if (len(ids) != len(users) or
                any(not isinstance(uid, str) or not uid for uid in ids) or
                len(set(ids)) != len(ids)):
            raise ValueError("users_shape")
        report["users_checked"] = len(ids)
        for uid in ids:
            for kind in ("Movie", "Series"):
                requested_kind = kind
                stage = "items"
                start = 0
                expected = None
                seen = set()
                while True:
                    page = fetch(f"/Users/{uid}/Items", {
                        "Recursive": "true", "IncludeItemTypes": kind,
                        "Fields": "Path,Tags", "StartIndex": start,
                        "Limit": PAGE_SIZE,
                    })
                    report["pages_checked"] += 1
                    if not isinstance(page, dict):
                        raise ValueError("page_shape")
                    total = page.get("TotalRecordCount")
                    items = page.get("Items")
                    if (type(total) is not int or total < 0 or
                            total > MAX_ITEMS_PER_USER_KIND or
                            not isinstance(items, list) or
                            (expected is not None and total != expected) or
                            ("StartIndex" in page and
                             (type(page["StartIndex"]) is not int or
                              page["StartIndex"] != start))):
                        raise ValueError("pagination_metadata")
                    if expected is None:
                        expected = total
                    if len(items) != min(PAGE_SIZE, total - start):
                        raise ValueError("page_length")
                    for item in items:
                        if not isinstance(item, dict):
                            raise ValueError("item_fields")
                        item_id = item.get("Id")
                        path = item.get("Path")
                        tags = item.get("Tags")
                        data = item.get("UserData")
                        if not isinstance(item_id, str) or not item_id:
                            raise ValueError("item_id")
                        if item_id in seen:
                            raise ValueError("duplicate_item_id")
                        if not isinstance(path, str) or not path.startswith("/"):
                            raise ValueError("item_path")
                        if ("//" in path or chr(92) in path or
                                any(part in (".", "..") for part in path.split("/"))):
                            raise ValueError("unsafe_item_path")
                        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
                            raise ValueError("item_tags")
                        if not isinstance(data, dict):
                            raise ValueError("user_data")
                        if type(data.get("IsFavorite")) is not bool:
                            raise ValueError("favorite_field")
                        if type(data.get("Played")) is not bool:
                            raise ValueError("played_field")
                        if type(data.get("PlayCount")) is not int or data["PlayCount"] < 0:
                            raise ValueError("play_count_field")
                        if item.get("Type") is not None and item["Type"] != kind:
                            value = item["Type"]
                            returned_kind = (value if type(value) is str and
                                             value in {"Movie", "Series", "Episode",
                                                       "Season", "Folder", "CollectionFolder",
                                                       "BoxSet", "Video", "Trailer",
                                                       "MusicVideo"} else "other_or_invalid")
                            raise ValueError("item_type")
                        seen.add(item_id)
                    count = len(items)
                    report["items_checked"] += count
                    report["movie_items_checked" if kind == "Movie"
                           else "series_items_checked"] += count
                    start += count
                    if start == total:
                        break
        report["scan_complete"] = True
    except requests.HTTPError as exc:
        code = getattr(getattr(exc, "response", None), "status_code", None)
        report["failure_category"] = ("http_" + str(code)
                                      if type(code) is int else "http_error")
    except requests.Timeout:
        report["failure_category"] = "timeout"
    except requests.ConnectionError:
        report["failure_category"] = "connection_error"
    except requests.RequestException:
        report["failure_category"] = "request_error"
    except (ValueError, TypeError, KeyError) as exc:
        report["failure_category"] = "invalid_or_incomplete_response"
        # Only fixed internal labels are permitted; never echo exception text.
        allowed = {"users_shape", "page_shape", "pagination_metadata",
                   "page_length", "item_fields", "item_id", "duplicate_item_id",
                   "item_path", "unsafe_item_path", "item_tags", "user_data",
                   "favorite_field", "played_field", "play_count_field", "item_type"}
        report["validation_failure"] = (str(exc) if type(exc) is ValueError
                                        and str(exc) in allowed else "unexpected_shape")
    if not report["scan_complete"]:
        report["failure_stage"] = stage
        if report.get("validation_failure") == "item_type":
            report["requested_item_type"] = requested_kind
            report["returned_item_type"] = returned_kind
    return report


def main():
    url = os.environ.get("JELLYFIN_HOST_URL", "").rstrip("/")
    token = os.environ.get("JELLYFIN_API_TOKEN", "").strip()
    parsed = urlparse(url)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or
            parsed.username or parsed.password or not token):
        print("Jellyfin host and token required in environment.", file=sys.stderr)
        return 2
    session = requests.Session()
    session.trust_env = False
    session.headers.update({"Authorization": (
        "MediaBrowser Client=MediaCollectionAuditor, "
        "Device=Unraid, DeviceId=sqlite-full-readonly-scan, "
        "Version=1.0, Token=" + token
    )})

    def fetch(path, params):
        response = session.get(url + path, params=params, timeout=20)
        response.raise_for_status()
        return response.json()

    result = scan(fetch)
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["scan_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
