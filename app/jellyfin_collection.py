"""Experimental Jellyfin collection boundary; read-only, non-authorizing.

fetch(path, params) must be a trusted transport supplied by the caller.
No production execution uses this module. Missing/partial data fails closed.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath

from app.jellyfin_signals import review_jellyfin_observation

PAGE_SIZE = 100
FIELDS = ("played", "favorite", "disliked", "keep", "keep_all", "protected")
DEFAULT_TAG_NAMES = {"keep": "keep", "disliked": "not-at-all",
                     "keep_all": "keep-all-seasons", "protected": "keep-forever"}


def validated_tag_names(tag_names=None):
    names = DEFAULT_TAG_NAMES if tag_names is None else tag_names
    if (not isinstance(names, dict) or set(names) != set(DEFAULT_TAG_NAMES)
            or any(not isinstance(value, str) or not value or value.strip() != value
                   or len(value) > 128 or any(ord(c) < 32 or ord(c) == 127 for c in value)
                   for value in names.values())):
        raise ValueError("Explicit valid Jellyfin tag mapping required")
    result = {key: value.lower() for key, value in names.items()}
    if len(set(result.values())) != len(result):
        raise ValueError("Conflicting Jellyfin tag names")
    return result


def collect_title_observation(*, fetch, jellyfin_type, folder, media_key, now,
                              page_size=PAGE_SIZE, tag_names=None, excluded_series_path=None):
    if (jellyfin_type not in ("Movie", "Series") or not isinstance(folder, str)
            or not folder or folder in (".", "..") or "/" in folder or chr(92) in folder):
        raise ValueError("Movie/Series and single folder name required")
    if not callable(fetch) or type(page_size) is not int or page_size < 1 or page_size > 1000:
        raise ValueError("Invalid Jellyfin collection configuration")
    if not isinstance(now, datetime) or now.tzinfo is not None:
        raise ValueError("Naive observation clock required")
    tag_names = validated_tag_names(tag_names)
    if excluded_series_path is not None and (jellyfin_type != 'Series'
            or not isinstance(excluded_series_path, str)
            or not excluded_series_path.startswith('/')
            or PurePosixPath(excluded_series_path).name != folder):
        raise ValueError('Exact staged series path required')
    blockers = []
    matched = []
    near_match = False
    try:
        users = fetch("/Users", None)
        if not isinstance(users, list) or not users:
            raise ValueError("Users response missing or empty")
        ids = [user.get("Id") for user in users if isinstance(user, dict)]
        if (len(ids) != len(users) or any(not isinstance(uid, str) or not uid for uid in ids)
                or len(set(ids)) != len(ids)):
            raise ValueError("Invalid or duplicate users")
        for uid in ids:
            start = 0
            seen_ids = set()
            expected_total = None
            while True:
                data = fetch(f"/Users/{uid}/Items", {
                    "Recursive": "true", "IncludeItemTypes": jellyfin_type,
                    "ExcludeItemTypes": "BoxSet",
                    "CollapseBoxSetItems": "false",
                    "Fields": "Path,Tags", "StartIndex": start, "Limit": page_size,
                })
                if not isinstance(data, dict) or type(data.get("TotalRecordCount")) is not int:
                    raise ValueError("Pagination metadata missing")
                if ("StartIndex" in data and
                        (type(data["StartIndex"]) is not int or data["StartIndex"] != start)):
                    raise ValueError("Jellyfin page offset mismatch")
                total = data["TotalRecordCount"]
                if expected_total is None:
                    expected_total = total
                elif total != expected_total:
                    raise ValueError("Jellyfin result count changed during pagination")
                items = data.get("Items")
                if (total < 0 or not isinstance(items, list) or
                        len(items) > page_size or start + len(items) > total or
                        (start < total and not items) or
                        (start < total and len(items) != min(page_size, total - start))):
                    raise ValueError("Incomplete Jellyfin page")
                for item in items:
                    if not isinstance(item, dict):
                        raise ValueError("Invalid Jellyfin item")
                    item_id, path = item.get("Id"), item.get("Path")
                    tags, user_data = item.get("Tags"), item.get("UserData")
                    if (not isinstance(item_id, str) or not item_id or item_id in seen_ids
                            or not isinstance(path, str) or not path.startswith("/")
                            or any(part in (".", "..") for part in path.split("/"))
                            or "//" in path or chr(92) in path
                            or not isinstance(tags, list)
                            or any(not isinstance(tag, str) for tag in tags)
                            or not isinstance(user_data, dict)
                            or type(user_data.get("IsFavorite")) is not bool
                            or type(user_data.get("Played")) is not bool
                            or type(user_data.get("PlayCount")) is not int
                            or user_data["PlayCount"] < 0
                            ):
                        raise ValueError("Missing or inconsistent Jellyfin item fields")
                    seen_ids.add(item_id)
                    # Jellyfin can return BoxSet collections despite type filters.
                    # Never match these as media titles; all fields above must
                    # still be valid or the entire observation fails closed.
                    if item.get("Type") == "BoxSet":
                        continue
                    if item.get("Type") is not None and item["Type"] != jellyfin_type:
                        raise ValueError("Unexpected Jellyfin media type")
                    pure = PurePosixPath(path)
                    name = pure.parent.name if jellyfin_type == "Movie" else pure.name
                    import unicodedata
                    if name!=folder and unicodedata.normalize('NFC',name).casefold()==unicodedata.normalize('NFC',folder).casefold():
                        near_match=True
                    if name == folder and path != excluded_series_path:
                        matched.append((uid, item_id, path, tags, user_data))
                start += len(items)
                if start == total:
                    break
    except (Exception) as exc:
        # Fail closed on transport errors and malformed responses.
        blockers.append("jellyfin_collection_incomplete")
        blockers.append(type(exc).__name__)
    if not matched:
        blockers.append("jellyfin_title_unmatched")
    if matched:
        if {uid for uid, *_ in matched} != set(ids):
            blockers.append("jellyfin_title_user_coverage_incomplete")
        # One logical Jellyfin item may appear for multiple users. Distinct
        # item IDs or paths are ambiguous, even if folder names match.
        identities = {(item_id, path) for _, item_id, path, _, _ in matched}
        if len(identities) != 1:
            blockers.append("jellyfin_title_ambiguous")
    signals = {name: False for name in FIELDS}
    observed_tags = set()
    if not blockers:
        for _, _, _, tags, data in matched:
            normalized = {tag.lower() for tag in tags}
            observed_tags.update(normalized)
            signals["played"] |= data["Played"] or data["PlayCount"] > 0
            signals["favorite"] |= data["IsFavorite"]
            signals["keep"] |= tag_names["keep"] in normalized
            signals["disliked"] |= tag_names["disliked"] in normalized
            signals["keep_all"] |= tag_names["keep_all"] in normalized
            signals["protected"] |= tag_names["protected"] in normalized
        if signals["protected"]:
            signals["keep_all"] = True
    absence_verified = blockers == ['jellyfin_title_unmatched'] and not near_match
    observation = {
        "media_key": media_key, "observed_at": now,
        "coverage_complete": not blockers, "request_succeeded": not blockers,
        "signals": signals if not blockers else None,
    }
    contract = review_jellyfin_observation(
        observation=observation, media_key=media_key, now=now)
    return {
        "status": "blocked" if blockers or contract["blockers"] else "shape_valid_untrusted",
        "blockers": blockers + contract["blockers"],
        "signals": contract["signals"] if not blockers else None,
        "observed_tags": tuple(sorted(observed_tags)) if not blockers else None,
        "identity": (matched[0][1], matched[0][2]) if not blockers else None,
        "absence_verified": absence_verified,
        "authorization": "not_authorized",
        "production_activation": "disabled",
        "read_only": True,
    }
