"""Fresh decision boundary for scheduled plans; no filesystem move or permit.

Providers must be read-only, trusted dependencies. Invoking a protection provider
here prevents reuse of the scan's signals; it cannot prove a provider bypassed
its cache. Source/destination validation and guarded intent handling are separate
requirements before any actual execution.
"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import math
import os
from time import monotonic

from app.sqlite_jellyfin_signal_contract import SIGNAL_FIELDS
from app.sqlite_lifecycle_checkpoint_plan import CLOCKS
from app.sqlite_lifecycle_decision_bridge import review_decision
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_scheduled_plan import PlannedMove, ScheduledPlan
from app.sqlite_state import validate_snapshot


@dataclass(frozen=True)
class ProtectionRead:
    available: bool
    signals: dict | None


def recheck_scheduled_move(*, plan, move, read_tracking, fetch_protection,
                           clock=datetime.now, timer=monotonic,
                           maximum_protection_seconds=30):
    """Read current tracking, freshly fetch signals, then re-read tracking.

    Returns only a non-authorizing advisory report. No supplied flag can turn
    this into filesystem permission. Plans are ephemeral and process-bound.
    """
    if (type(maximum_protection_seconds) not in (int, float)
            or not math.isfinite(maximum_protection_seconds) or maximum_protection_seconds <= 0):
        raise ValueError('Positive finite protection-read budget required')
    base = {'authorization': 'not_authorized', 'production_activation': 'disabled',
            'production_authorized': False, 'read_only': True}

    def blocked(reason):
        return {**base, 'status': 'blocked', 'reason': reason}

    if (not isinstance(plan, ScheduledPlan) or not isinstance(move, PlannedMove)
            or move not in plan.moves):
        return blocked('move_not_in_plan')
    if plan.process_id != os.getpid():
        return blocked('plan_process_changed')

    def current_tick():
        tick = timer()
        if (not math.isfinite(tick) or not plan.created_tick <= tick < plan.deadline_tick):
            raise RuntimeError('plan_expired_or_clock_changed')
        return tick

    def tracking():
        snapshot, revision = read_tracking()
        snapshot = deepcopy(snapshot)
        validate_snapshot(snapshot)
        if type(revision) is not int or revision != plan.revision:
            raise RuntimeError('tracking_revision_changed')
        if snapshot.get(INTENTS_KEY):
            raise RuntimeError('unresolved_sqlite_operation')
        if snapshot[CLOCKS[move.source_stage]].get(move.media_key) != move.source_clock:
            raise RuntimeError('source_clock_changed')
        if any(move.media_key in snapshot[section] for stage, section in CLOCKS.items()
               if stage != move.source_stage):
            raise RuntimeError('conflicting_lifecycle_clock')
        return snapshot

    # Keep exception payloads private: providers may include URLs or credentials.
    try:
        started = current_tick()
    except Exception:
        return blocked('plan_expired_or_clock_changed')
    try:
        before = tracking()
    except Exception:
        return blocked('tracking_not_current')
    try:
        current_tick()
        protection = deepcopy(fetch_protection(move))
    except Exception:
        return blocked('fresh_protection_unavailable')
    try:
        finished = current_tick()
        if not 0 <= finished - started < maximum_protection_seconds:
            return blocked('protection_read_deadline_exceeded')
    except Exception:
        return blocked('plan_expired_or_clock_changed')
    if (not isinstance(protection, ProtectionRead) or protection.available is not True
            or not isinstance(protection.signals, dict)
            or not SIGNAL_FIELDS.issubset(protection.signals)
            or any(type(protection.signals[key]) is not bool for key in SIGNAL_FIELDS)
            or protection.signals['protected'] and not protection.signals['keep_all']):
        return blocked('fresh_protection_incomplete')
    try:
        after = tracking()
        if after != before:
            return blocked('tracking_changed_during_refresh')
        decision = review_decision(after, move.media_key, move.source_stage, clock(),
            move.threshold_days, protection.signals, plan.favorites_trigger_keep)
        if current_tick() - started >= maximum_protection_seconds:
            return blocked('protection_read_deadline_exceeded')
    except Exception:
        return blocked('tracking_or_plan_not_current')
    if decision['status'] != 'advisory' or decision['action'] != move.action:
        return blocked('fresh_decision_changed')
    return {**base, 'status': 'revalidated_advisory', 'reason': 'fresh_decision_matches',
            'filesystem_validation_required': True, 'guarded_intent_required': True}
