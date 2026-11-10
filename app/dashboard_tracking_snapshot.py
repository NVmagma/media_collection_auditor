"""Read tracking once and prepare separate copies for the dashboard."""
from dataclasses import dataclass, field
from datetime import datetime
import json
import re
from pathlib import Path
from typing import Callable

if __package__:
    from .json_validation import parse_unique_json
    from .tracking_schema import SECTIONS, validate_snapshot
else:  # web.py also imports this module with app/ on the Python path.
    from json_validation import parse_unique_json
    from tracking_schema import SECTIONS, validate_snapshot


@dataclass(frozen=True)
class DashboardTrackingSnapshot:
    source: str
    revision: int | None
    _payload: bytes = field(repr=False)
    _verify: Callable[[], object] = field(repr=False, compare=False)

    @property
    def state(self):
        """Give each caller its own copy of the same captured tracking data."""
        return parse_unique_json(self._payload)

    def verify_current(self):
        """Recheck the original tracking file when needed."""
        self._verify()

    @property
    def metadata(self):
        return {"source": self.source, "revision": self.revision,
                "storage_authority": "json", "production_activation": "disabled"}


def _encode(state):
    if not isinstance(state, dict):
        raise RuntimeError("Dashboard tracking snapshot invalid")
    normalized = dict(state)
    for section in SECTIONS:
        normalized.setdefault(section, {})
    validate_snapshot(normalized)
    return json.dumps(state, ensure_ascii=True, allow_nan=False,
                      sort_keys=True, separators=(",", ":")).encode("ascii")


def read_json_dashboard_snapshot(path, *, require_existing=False):
    """Read JSON tracking once and keep the old missing-section format supported."""
    path = Path(path)
    try:
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            if require_existing or path.is_symlink() or any(path.parent.glob(".auditor_state_*.tmp")):
                raise RuntimeError("Interrupted or unavailable dashboard state")
            raw = b"{}"
        payload = _encode(parse_unique_json(raw))
    except (OSError, ValueError, TypeError, RuntimeError, UnicodeError) as exc:
        raise RuntimeError("Dashboard tracking state is unreadable; displayed lifecycle dates may be incomplete") from exc
    return DashboardTrackingSnapshot("json", None, payload, lambda: None)






def lifecycle_clock(value, *, limit=None, now=None):
    """Show the saved date without guessing from a folder or another stage.

    Dates without a time-zone offset keep their original local meaning. Dates
    with an offset keep that offset, including when calculating age in Removal.
    """
    from datetime import datetime, timedelta
    result={'since_display':'Not yet tracked','since_basis':'No saved clock for this stage',
            'clock_status':'missing','elapsed_days':None,'deadline_days':None,
            'due':False,'next_review_date':None,'next_review_display':None}
    if value is None:return result
    try:
        start=datetime.fromisoformat(value.replace('Z','+00:00'))
    except (ValueError,TypeError,AttributeError,OverflowError):
        return {**result,'since_display':'Invalid saved date','since_basis':'Saved clock needs review',
                'clock_status':'invalid'}
    result.update(since_display=start.strftime('%m/%d/%Y %H:%M'),clock_status='recorded',
        since_basis='Local wall time as recorded' if start.tzinfo is None else 'Recorded offset '+start.strftime('%z'))
    current=now if now is not None else datetime.now(start.tzinfo)
    try:
        if start>current:
            return {**result,'clock_status':'future','since_basis':result['since_basis']+'; date is in the future'}
        result['elapsed_days']=(current-start).days
        if limit is not None:
            if type(limit) is not int or limit<0:raise ValueError('Nonnegative stage duration required')
            result.update(deadline_days=max(0,limit-result['elapsed_days']),due=result['elapsed_days']>=limit)
            try:
                review=(start+timedelta(days=limit)).date()
                result.update(next_review_date=review.isoformat(),next_review_display=review.strftime('%m/%d/%Y'))
            except OverflowError:pass
    except (ValueError,TypeError,OverflowError):
        result.update(clock_status='unavailable',elapsed_days=None,deadline_days=None,due=False)
    return result


def observation_datetime(value, timezone_name=None):
    """Format progress dates in the selected time zone without changing old local dates."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    if not value:return 'Not recorded in this process'
    try:parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    except (ValueError,TypeError,AttributeError,OverflowError):return 'Invalid recorded time'
    label=None
    if parsed.tzinfo is not None and timezone_name:
        try:
            parsed=parsed.astimezone(ZoneInfo(timezone_name));label=timezone_name
        except (ValueError,TypeError,KeyError):pass
    text=parsed.strftime('%m/%d/%Y %H:%M')
    if label:return text+' '+label
    offset=parsed.strftime('%z')
    if offset:text+=' UTC'+offset[:3]+':'+offset[3:]
    return text


def summarize_dashboard_clocks(state, stages, warnings, *, libraries, tracking_available=True):
    """Summarize the captured folders without scanning again or changing dates.

    A record missing from one stage does not prove that media was deleted.
    Unreadable tracking or folders mean coverage is unknown, not zero.
    """
    sections={'Waiting':'first_seen','Holding':'queued','Removal':'in_removal','Keep':'keep_seen'}
    rows=[]
    totals={key:0 for key in ('missing_dates','invalid_dates','future_dates','records_without_stage_folder')}
    complete=tracking_available
    for library in libraries:
        for stage,section in sections.items():
            items=[item for item in stages.get(stage,[]) if item['library']==library]
            unavailable=any(message.startswith(library+' '+stage+':') for message in warnings)
            status='directory_unavailable' if unavailable else 'observed' if tracking_available else 'tracking_unavailable'
            row={'library':library,'stage':stage,'status':status,'folders':None if unavailable else len(items)}
            for key in totals:row[key]=None
            if status=='observed':
                row.update(missing_dates=0,invalid_dates=0,future_dates=0,records_without_stage_folder=0)
                present=set()
                for item in items:
                    present.add(('TV/' if library=='TV' else '')+item['title'])
                    clock=lifecycle_clock(item.get('since'))
                    key={'missing':'missing_dates','invalid':'invalid_dates','future':'future_dates'}.get(clock['clock_status'])
                    if key:row[key]+=1
                recorded={key for key in state.get(section,{}) if key.startswith('TV/')==(library=='TV')}
                row['records_without_stage_folder']=len(recorded-present)
                for key in totals:totals[key]+=row[key]
            else:complete=False
            rows.append(row)
    return {'rows':rows,'complete':complete,'freshness_verified':False,**totals}


def dashboard_overview(stages, coverage, *, libraries, tracking_available=True, limit=5):
    """Build the Overview lists from the folder data already collected.

    Sort Waiting by recorded elapsed days, then title and library. Holding uses
    the estimated calendar date. Put unknown dates last without inventing one.
    Do not collect more data or save tracking here.
    """
    if type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError('Overview limit must be between one and ten')
    enabled = set(libraries)
    result = {'freshness_verified': False, 'count_basis': 'observed_folders', 'lists': {}, 'attention': []}
    for stage, name in (('Holding', 'leaving_soon'), ('Waiting', 'oldest_waiting')):
        source = [item for item in stages.get(stage, []) if item['library'] in enabled]
        incomplete = any(row['stage'] == stage and row['library'] in enabled
                         and row['status'] != 'observed' for row in coverage['rows'])
        if not tracking_available:
            result['lists'][name] = {'status': 'unavailable', 'items': None,
                'observed_folders': len(source), 'more': 0, 'unusable_dates': None}
            continue
        def sort_key(item):
            if stage == 'Holding':
                known = item.get('clock_status') == 'recorded' and bool(item.get('next_review_date'))
                date = item['next_review_date'] if known else ''
            else:
                elapsed = item.get('elapsed_days')
                known = item.get('clock_status') == 'recorded' and type(elapsed) is int and elapsed >= 0
                date = -elapsed if known else 0
            return (not known, date, item['title'].casefold(), item['library'])
        ordered = sorted(source, key=sort_key)
        rows = [{key: item.get(key) for key in ('title', 'library', 'clock_status', 'since_display',
                    'since_basis', 'next_review_display')} | {'stage': stage} for item in ordered[:limit]]
        result['lists'][name] = {'status': 'partial' if incomplete else 'observed', 'items': rows,
            'observed_folders': len(source), 'more': max(0, len(source) - limit),
            'unusable_dates': sum(sort_key(item)[0] for item in source)}
    attention = result['attention']
    if not tracking_available:
        attention.append({'title': 'Tracking unavailable',
            'detail': 'Saved dates and tracking totals cannot be verified. Review the tracking error before relying on this display.',
            'target': 'clock-coverage'})
    if not coverage['complete']:
        attention.append({'title': 'Coverage is incomplete',
            'detail': 'Some tracking or directory observations are unavailable. Counts below cover only readable inputs.',
            'target': 'clock-coverage'})
    prefix = 'At least ' if not coverage['complete'] else ''
    for count, singular, plural, detail in (
        (coverage['missing_dates'], 'folder has no saved stage date', 'folders have no saved stage date', 'Existing dates are preserved. No folder date is substituted.'),
        (coverage['invalid_dates'] + coverage['future_dates'], 'saved date needs review', 'saved dates need review', 'Invalid or future dates are not used as reliable lifecycle ages.'),
        (coverage['records_without_stage_folder'], 'record has no matching stage folder', 'records have no matching stage folder', 'Review renamed or absent folders; this does not prove media was deleted.')):
        if count:
            attention.append({'title': prefix + str(count) + ' ' + (singular if count == 1 else plural), 'detail': detail, 'target': 'clock-coverage'})
    return result


# Prepare scheduler records for display without adding a container dependency.
_SCAN_REASON = {
    'worker_return': 'The worker returned a recorded result. This does not verify live inventory freshness.',
    'blocked_or_uncertain': 'The attempt stopped with a blocked or uncertain outcome. Review logs and retained operation state; do not assume it is safe to replay.',
    'observation_unavailable': 'Completion timing could not be recorded. This is not proof of a successful scan.'}


def _scan_counter(value):
    return value if type(value) is int and 0 <= value <= 100000 else None


def _scan_time(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 80:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed if parsed.tzinfo is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


def _scan_entry(record, zone, *, title_details=True):
    """Return only known summary fields and limited title results, without raw errors or payloads."""
    if __package__:
        from .scan_details import project_details
    else:
        from scan_details import project_details
    start, finish = _scan_time(record.get('started_at')), _scan_time(record.get('finished_at'))
    duration = None
    if start is not None and finish is not None:
        try:
            seconds = (finish - start).total_seconds()
            if 0 <= seconds <= 1e9:
                duration = round(seconds, 2)
        except (ValueError, TypeError, OverflowError):
            pass
    preview = record.get('dry_run')
    mode = 'Preview' if preview is True else 'Live (recorded)' if preview is False else 'Not reported'
    result, basis, trigger = (record.get(key) for key in ('result', 'result_basis', 'trigger'))
    label, group = 'Outcome not recorded', 'unknown'
    if result == 'completed':
        if duration is None:
            label, group = 'Completion unverified', 'review'
        else:
            label, group = ('Preview completed' if preview is True else 'Attempt completed'), 'completed'
    elif result == 'failed':
        label, group = ('Blocked / uncertain' if basis == 'blocked_or_uncertain' else 'Attempt failed'), 'review'
    elif result == 'stopped':
        label, group = 'Attempt stopped', 'review'
    reason = _SCAN_REASON.get(basis, 'No detailed outcome reason was recorded.') if isinstance(basis, str) else 'No detailed outcome reason was recorded.'
    if result == 'completed' and duration is None:
        reason = 'A completed result was recorded, but valid start/finish timing is unavailable. Completion cannot be confirmed from these observations.'
    if result == 'failed':
        stage_label = {
            'worker':'starting or admitting the worker',
            'collection':'checking folders, clocks, and service data',
            'candidate_preparation':'preparing a selected move',
            'move_and_sync':'moving a title or verifying its Arr update',
            'deletion_preparation':'preparing a Removal deletion',
            'arr_deletion':'verifying an Arr deletion',
            'metadata_quarantine':'quarantining metadata',
            'tv_season_retention':'processing TV seasons',
            'storage_revalidation':'rechecking saved tracking',
        }.get(record.get('failure_stage')) if isinstance(record.get('failure_stage'),str) else None
        if stage_label: reason += ' The failure was recorded while '+stage_label+'.'
    trigger_label = {'scheduled': 'Daily schedule', 'manual': 'Manual preview' if preview is True else 'Manual request',
                     'startup': 'Startup', 'rescue': 'Manual rescue'}.get(trigger, 'Not reported') if isinstance(trigger, str) else 'Not reported'
    duration_display = 'Not recorded'
    if duration is not None:
        minutes, seconds = divmod(duration, 60)
        duration_display = f'{int(minutes)}m {seconds:g}s' if minutes else f'{seconds:g}s'
    return {'attempt_id': record.get('id') if isinstance(record.get('id'),str) and re.fullmatch('[0-9a-f]{32}',record['id']) else None,
        'label': label, 'group': group, 'mode': mode, 'trigger': trigger_label,
        'started': observation_datetime(start.isoformat(), zone) if start else 'Not recorded',
        'finished': observation_datetime(finish.isoformat(), zone) if finish else 'Not recorded',
        'duration': duration, 'duration_display': duration_display, 'reason': reason,
        'moves_proposed': _scan_counter(record.get('moves_proposed')),
        'discovery_changes': _scan_counter(record.get('discovery_changes')),
        'metadata_quarantines_completed': _scan_counter(record.get('metadata_quarantines_completed')),
        'deletions_completed': _scan_counter(record.get('deletions_completed')),
        'deletions_proposed': _scan_counter(record.get('deletions_proposed')),
        'moves_completed': _scan_counter(record.get('moves_completed')),
        'arr_completed': _scan_counter(record.get('arr_completed')),
        'title_details': project_details(record.get('title_details')) if title_details else None}


def build_scan_view(run, history, *, timezone_name=None, title_details=True):
    """Render only the supplied results. Do not fall back to reading files, services, or history."""
    run = run if isinstance(run, dict) else {}
    if run.get('status') == 'unavailable':
        state, detail = 'Unavailable', 'No current scheduler observation is available.'
    elif run.get('running') is True:
        state, detail = 'Running', 'An attempt is in progress. Final counts are not available yet.'
    elif run.get('queued') is True:
        state, detail = 'Queued', 'A request is queued; this is not a completed scan.'
    elif run.get('scheduler_state') == 'blocked':
        state, detail = 'Blocked', 'The scheduler needs review before another attempt can proceed.'
    elif run.get('scheduler_state') == 'missed_slot_skipped':
        state, detail = 'Slot missed', 'The daily slot was missed. This observation does not represent a completed scan or authorize catch-up.'
    elif run.get('running') is False and run.get('queued') is False:
        state, detail = 'Waiting', 'No attempt is currently running or queued.'
    else:
        state, detail = 'Unavailable', 'Current running and queued state was not reported.'
    valid_history = isinstance(history, list)
    rows = [_scan_entry(record, timezone_name, title_details=title_details) for record in history[:100] if isinstance(record, dict)] if valid_history else []
    scope=run.get('history_scope')
    available = valid_history and (scope == 'current_process' or scope == 'persistent' and run.get('history_persistent') is True) and (not history or bool(rows))
    return {'current_state': state, 'current_detail': detail, 'history_available': available,
        'history_partial': valid_history and any(not isinstance(record, dict) for record in history[:100]),
        'rows': rows if available else [], 'latest': rows[0] if available and rows else None,
        'history_scope': scope if available else 'unavailable', 'freshness_verified': False,
        'skipped_title_count': None, 'blocked_title_count': None}
