"""Candidate daily service loop; production activation remains sealed."""
from datetime import datetime, timezone
import os

from app.sqlite_backend_gate import require_sqlite_production_activation
from app.sqlite_scheduled_production import production_cycle_step, run_requested_preview
from app.sqlite_scheduled_worker_cycle import ScheduledWorkerCycle


def run_daily_service(*, apply_settings):
    """Reload effective settings on wakes; manual requests are preview-only.

    Bounded waits permit settings reloads even without a manual wake. This loop
    never runs in deployed JSON mode and cannot be entered through environment
    selection while the release gate is closed.
    """
    require_sqlite_production_activation()
    from run_control import wait_for_run
    from app.sqlite_scheduled_observations import COORDINATOR
    cycle = ScheduledWorkerCycle()
    while True:
        apply_settings()
        if os.environ.get('AUDITOR_STATE_BACKEND', 'json') != 'sqlite':
            return
        now = datetime.now(timezone.utc)
        try:
            result = production_cycle_step(cycle=cycle, settings=dict(os.environ), now=now, observer=COORDINATOR)
            run_requested_preview(settings=dict(os.environ), now=datetime.now(timezone.utc), observer=COORDINATOR)
            delay = max(0, (result.next_run - datetime.now(timezone.utc)).total_seconds())
        except Exception:
            # No raw connection errors/settings/token details in worker logs.
            # The cycle advances before dispatch; claims/intents are retained.
            COORDINATOR.cancel_pending_preview()
            print('[SQLITE SCHEDULER] Attempt blocked or uncertain; no automatic replay.', flush=True)
            delay = 30
        wait_for_run(min(30, delay))
