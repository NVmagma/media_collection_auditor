"""Aggregate-only live coverage probe; never authorizes or writes state."""
from collections import Counter
from datetime import datetime

from app.sqlite_jellyfin_preview_bridge import preview_with_collected_jellyfin
from app.sqlite_lifecycle_checkpoint_plan import CLOCKS
from app.state_store import GuardedSQLiteStateStore


def probe_coverage(database, fetch, *, now=None):
    """Map standard bare movie / TV-prefixed keys, using one cached scan.

    Unknown key formats remain uncovered. Cache scope is one invocation only;
    this is advisory coverage, not proof of a transactional Jellyfin snapshot.
    """
    now = datetime.now() if now is None else now
    snapshot, revision = GuardedSQLiteStateStore(database).load_with_revision()
    keys = {key for section in CLOCKS.values() for key in snapshot[section]}
    requests = {}
    for key in sorted(keys):
        kind, folder = ("Series", key[3:]) if key.startswith("TV/") else ("Movie", key)
        if folder and folder not in (".", "..") and "/" not in folder and chr(92) not in folder:
            requests[key] = {"jellyfin_type": kind, "folder": folder}

    cache = {}
    failures = set()

    def cached_fetch(path, params):
        key = (path, tuple(sorted((params or {}).items())))
        if key in failures:
            raise RuntimeError("Jellyfin scan unavailable")
        if key not in cache:
            if len(cache) + len(failures) >= 10000:
                raise RuntimeError("Jellyfin scan request budget exceeded")
            try:
                cache[key] = fetch(path, params)
            except Exception:
                failures.add(key)
                raise RuntimeError("Jellyfin scan unavailable") from None
        return cache[key]

    result = preview_with_collected_jellyfin(
        database=database, now=now, thresholds={stage: 0 for stage in CLOCKS},
        requests=requests, fetch=cached_fetch)
    # Mapping and decision preview must refer to the same state revision.
    changed = revision != result["preview"]["revision"]
    coverage = result["coverage"]
    reasons = Counter(reason for row in coverage["titles"] for reason in row["blockers"])
    if changed:
        reasons["sqlite_revision_changed"] += 1
    return {
        "status": "blocked" if changed or result["status"] == "blocked" else "advisory_only",
        "coverage_complete": coverage["complete"] and not changed,
        "tracked_titles": coverage["tracked_titles"],
        "covered_titles": 0 if changed else coverage["covered_titles"],
        "blocked_titles": coverage["tracked_titles"] if changed else coverage["blocked_titles"],
        "blocker_counts": dict(sorted(reasons.items())),
        "request_count": len(cache) + len(failures),
        "read_only": True,
        "production_authorized": False,
        "production_activation": "disabled",
        "freshness_independently_verified": False,
    }
