"""Offline, redacted status contract; no network endpoint or action authority."""
from datetime import datetime, timezone, timedelta
if __package__:
    from .dashboard_tracking_snapshot import read_json_dashboard_snapshot
else:
    from dashboard_tracking_snapshot import read_json_dashboard_snapshot


def read_tracking_status(path):
    """Capture authoritative JSON once; counts are records, not live inventory.

    Missing state is unavailable even though the legacy dashboard permits a
    fresh installation's missing file. Unknown extension values never escape.
    """
    report = {
        "schema_version": 1, "status": "unavailable", "read_only": True,
        "storage_authority": "json", "production_activation": "disabled",
        "production_authorized": False, "freshness_verified": False,
        "count_basis": "tracking_records", "tracking_counts": None,
        "pending_operation_present": None,
    }
    try:
        state = read_json_dashboard_snapshot(path, require_existing=True).state
    except RuntimeError:
        return report
    report.update(
        status="advisory_only",
        tracking_counts={name: len(state.get(section, {})) for name, section in (
            ("waiting", "first_seen"), ("holding", "queued"),
            ("keep", "keep_seen"), ("removal", "in_removal"),
            ("arr_sync_pending", "arr_sync_pending"))},
        pending_operation_present="sqlite_pending_operations" in state,
    )
    return report


def audit_status_report(current):
    """Project coordinator observations onto a fixed schema, never free text.

    Coordinator history reads are best effort; this is not durable-history or
    collector-health verification, even when a prior result says completed.
    """
    report = {"schema_version": 1, "status": "unavailable", "read_only": True,
              "production_activation": "disabled", "production_authorized": False,
              "freshness_verified": False, "source": "coordinator_snapshot",
              "running": None, "queued": None, "rescuing": None,
              "last_result": None, "last_started": None, "last_finished": None,
              "next_run": None}
    flags = ("running", "queued", "rescuing")
    if not isinstance(current, dict) or any(type(current.get(key)) is not bool for key in flags):
        return report
    report.update(status="advisory_only", **{key: current[key] for key in flags})
    result = current.get("last_result")
    if isinstance(result, str) and result in ("completed", "failed"):
        report["last_result"] = result
    for key in ("last_started", "last_finished", "next_run"):
        value = current.get(key)
        if not isinstance(value, str) or len(value) > 64:
            continue
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is not None:
                report[key] = parsed.astimezone(timezone.utc).isoformat()
        except (ValueError, OverflowError):
            pass
    return report


def read_tracking_titles(path, view, *, holding_days=7):
    """Bounded opt-in title projection from one JSON read, without collection.

    Legacy timestamps are local wall time without an offset. Preserve that
    meaning rather than inventing UTC, elapsed seconds or a deletion deadline.
    """
    report = {"schema_version": 1, "status": "unavailable", "read_only": True,
              "production_activation": "disabled", "production_authorized": False,
              "storage_authority": "json", "freshness_verified": False,
              "count_basis": "tracking_records", "view": view, "limit": 10,
              "timestamp_basis": "legacy_local_wall_time", "items": None,
              "total_records": None, "truncated": None}
    if view not in ("oldest-waiting", "leaving-soon"):
        raise ValueError("Unknown title view")
    try:
        if type(holding_days) is not int or not 1 <= holding_days <= 36500:
            return report
        state = read_json_dashboard_snapshot(path, require_existing=True).state
        section = "first_seen" if view == "oldest-waiting" else "queued"
        entries = []
        for key, value in state.get(section, {}).items():
            # first_seen can remain present after a title enters another stage.
            if view == "oldest-waiting" and any(
                    key in state.get(other, {}) for other in ("queued", "keep_seen", "in_removal")):
                continue
            library = "TV" if key.startswith("TV/") else "Movies"
            title = key[3:] if library == "TV" else key
            # State extensions or malformed keys must never leak raw paths.
            if (not title or len(title) > 250 or title in (".", "..")
                    or any(c in title for c in ("/", "\\"))
                    or any(ord(c) < 32 or ord(c) == 127 for c in title)):
                return report
            since = datetime.fromisoformat(value)
            estimate = since + timedelta(days=holding_days) if view == "leaving-soon" else None
            entries.append((since, library, title, {
                "title": title, "library": library,
                "stage": "waiting" if view == "oldest-waiting" else "holding",
                "since": since.isoformat(),
                "estimated_removal_stage_at": estimate.isoformat() if estimate else None,
                "transition_authorized": False,
            }))
        entries.sort(key=lambda entry: entry[:3])
    except (RuntimeError, ValueError, TypeError, OverflowError):
        return report
    report.update(status="advisory_only", items=[entry[3] for entry in entries[:10]],
                  total_records=len(entries), truncated=len(entries) > 10)
    return report
