"""Offline, redacted status contract; no network endpoint or action authority."""
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
