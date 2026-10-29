"""Candidate daily service loop; production activation remains sealed."""
from datetime import datetime, timezone
import os

from app.sqlite_backend_gate import require_sqlite_production_activation
from app.sqlite_scheduled_production import production_cycle_step, run_requested_preview, run_requested_live
from app.sqlite_scheduled_worker_cycle import ScheduledWorkerCycle
from app.operational_notifications import NOTIFICATIONS


def run_daily_service(*, apply_settings):
    """Reload effective settings on wakes; explicit live requests share the durable daily claim.

    Bounded waits permit settings reloads even without a manual wake. This loop
    never runs in deployed JSON mode and cannot be entered through environment
    selection while the release gate is closed.
    """
    from app.sqlite_backend_gate import preview_release_enabled, live_release_enabled, scheduled_release_enabled
    if not scheduled_release_enabled():
        require_sqlite_production_activation()
    from run_control import wait_for_run
    from app.sqlite_scheduled_observations import COORDINATOR
    cycle = ScheduledWorkerCycle()
    notification_settings = dict(os.environ)
    while True:
        now = datetime.now(timezone.utc)
        phase = 'settings_review_required'
        try:
            apply_settings()
            if os.environ.get('AUDITOR_STATE_BACKEND', 'json') != 'sqlite':
                raise RuntimeError('Preview cannot select a different backend')
            require_sqlite_production_activation()
            notification_settings = dict(os.environ)
            NOTIFICATIONS.clear('settings_review_required')
            phase = 'scan_blocked_or_uncertain'
            result = production_cycle_step(cycle=cycle, settings=dict(os.environ), now=now, observer=COORDINATOR)
            manual_result = (run_requested_preview(settings=dict(os.environ), now=datetime.now(timezone.utc), observer=COORDINATOR)
                             if preview_release_enabled() else
                             run_requested_live(settings=dict(os.environ),now=datetime.now(timezone.utc),observer=COORDINATOR)
                             if live_release_enabled() else None)
            if getattr(result, 'status', None) == 'attempted' or manual_result is not None:
                if COORDINATOR.report().get('last_result') == 'completed':
                    NOTIFICATIONS.clear('scan_blocked_or_uncertain')
                else:
                    alert = NOTIFICATIONS.emit(notification_settings, 'scan_blocked_or_uncertain')
                    if alert['attempted']:
                        print('[NOTIFY] Operational alert ' + alert['status'] + '.', flush=True)
            delay = max(0, (result.next_run - datetime.now(timezone.utc)).total_seconds())
        except Exception:
            # No raw connection errors/settings/token details in worker logs.
            # The cycle advances before dispatch; claims/intents are retained.
            COORDINATOR.cancel_pending_preview()
            print('[SQLITE SCHEDULER] Attempt blocked or uncertain; no automatic replay.', flush=True)
            alert = NOTIFICATIONS.emit(notification_settings, phase)
            if alert['attempted']:
                print('[NOTIFY] Operational alert ' + alert['status'] + '.', flush=True)
            delay = 30
        wait_for_run(min(30, delay))
