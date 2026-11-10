from app.tracking_schema import has_pending_extension
"""Explicit atomic clock checkpoints after fresh trusted local verification.

Not an HTTP endpoint or worker entrypoint. A caller must freshly establish
inventory/content/protection evidence; a browser confirmation is not evidence.
"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime

from app.json_scan_control import KEY, _control
from app.lifecycle_stages import CLOCKS
from app.title_identity import validate_title_folder


@dataclass(frozen=True)
class ClockObservation:
    media_key: str
    stage: str
    previous: str | None
    observed_at: datetime
    reason: str


def apply_clock_observations(session, *, changes, now, verify_change):
    if (not isinstance(changes,(tuple,list)) or len(changes) > 100000
            or not isinstance(now,datetime) or now.tzinfo is not None or now > datetime.now()
            or not callable(verify_change)):
        raise ValueError('Explicit bounded clock observations required')
    session.verify()
    before = deepcopy(session.state)
    if (has_pending_extension(before) or before.get('arr_sync_pending')
            or KEY in before and _control(before)['journal'] is not None):
        raise RuntimeError('Pending operation requires review')
    seen = set()
    checked = deepcopy(changes)
    for change in checked:
        if (not isinstance(change,ClockObservation) or change.stage not in CLOCKS
                or not isinstance(change.media_key,str) or change.media_key in seen
                or not isinstance(change.observed_at,datetime) or change.observed_at.tzinfo is not None
                or change.observed_at > now or change.reason not in ('discovered','content_reset')):
            raise ValueError('Unique safe clock observation required')
        folder = change.media_key[3:] if change.media_key.startswith('TV/') else change.media_key
        validate_title_folder(folder)
        if folder.startswith('.'): raise ValueError('Media folder required')
        seen.add(change.media_key)
        section = CLOCKS[change.stage]
        matches = [key for key in CLOCKS.values() if change.media_key in before[key]]
        if change.reason == 'discovered':
            if matches or change.previous is not None or change.observed_at != now:
                raise RuntimeError('Discovery cannot replace or backdate a clock')
        elif (not change.media_key.startswith('TV/') or change.stage != 'Waiting'
                or matches != [section] or before[section][change.media_key] != change.previous
                or change.observed_at <= datetime.fromisoformat(change.previous)):
            raise RuntimeError('TV reset observation no longer matches tracking')
    # Finish all independent checks before changing tracking dates in memory.
    for change in checked:
        if verify_change(change) is not True:
            raise RuntimeError('Fresh clock evidence unavailable')
        session.verify()
        if session.state != before: raise RuntimeError('Tracking changed during clock verification')
    if checked:
        for change in checked:
            session.state[CLOCKS[change.stage]][change.media_key] = change.observed_at.isoformat()
        session.checkpoint()
    return {'status':'clock_observations_applied' if checked else 'no_clock_changes',
        'changed_dates':len(checked),'media_actions_performed':False,
        'arr_updates_sent':0,'scan_claims_modified':False}
