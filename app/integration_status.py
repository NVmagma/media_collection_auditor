"""Offline, redacted status contract; no network endpoint or action authority."""
from datetime import datetime, timezone
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
