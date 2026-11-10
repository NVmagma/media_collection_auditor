"""Report JSON worker readiness without enabling actions or changing media."""
def health_contract(summary, audit, counts):
    expected={name:counts[section] for name,section in
        (('waiting','first_seen'),('holding','queued'),('keep','keep_seen'),('removal','in_removal'),('arr_sync_pending','arr_sync_pending'))}
    if (summary.get('storage_authority')!='json' or summary.get('tracking_counts')!=expected
            or summary.get('pending_operation_present') is not False or summary.get('read_only') is not True
            or summary.get('freshness_verified') is not False
            or audit.get('storage_authority')!='json' or audit.get('worker_mode')!='json_serialized'
            or audit.get('execution_mode')!='scheduled_live_moves' or audit.get('execution_blocked') is not False
            or audit.get('running') is not False or audit.get('queued') is not False or not audit.get('next_run')
            or audit.get('maximum_actions')!=10 or audit.get('per_library_action_limit')!=5
            or audit.get('minimum_live_scan_interval_seconds')!=3600
            or audit.get('permanent_deletion_authorized') is not False):
        raise RuntimeError('JSON readiness or initial tracking parity unavailable')
