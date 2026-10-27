"""Detached tracking reads and read-only dashboard presentation projections."""
from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
from typing import Callable

if __package__:
    from .sqlite_json import parse_unique_json
    from .sqlite_state import SECTIONS, validate_snapshot
else:  # Production web.py also runs with app/ as its import root.
    from sqlite_json import parse_unique_json
    from sqlite_state import SECTIONS, validate_snapshot


@dataclass(frozen=True)
class DashboardTrackingSnapshot:
    source: str
    revision: int | None
    _payload: bytes = field(repr=False)
    _verify: Callable[[], object] = field(repr=False, compare=False)

    @property
    def state(self):
        """Each consumer receives its own copy of the same captured snapshot."""
        return parse_unique_json(self._payload)

    def verify_current(self):
        """Experimental SQLite comparisons must reject concurrent checkpoints."""
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
    """Read authoritative JSON once; preserve legacy missing-section shape."""
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


def read_experimental_sqlite_dashboard_snapshot(database):
    """Explicit rehearsal only. Never chosen from an environment/backend flag."""
    from app.sqlite_audit_session import RevisionedAuditSession
    from app.state_store import GuardedSQLiteStateStore
    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    state, revision = session.read_verified_snapshot()
    return DashboardTrackingSnapshot("sqlite_experimental", revision, _encode(state),
                                     session.read_verified_snapshot)


def compare_dashboard_snapshots(*, json_path, database, build_inventory):
    """Explicit read-only rehearsal of one dashboard builder against both sources.

    build_inventory is a trusted local read-only callback, never a network
    collector. Comparison does not select a backend or authorize actions.
    """
    if not callable(build_inventory):
        raise ValueError("Read-only dashboard inventory callback required")
    authoritative = read_json_dashboard_snapshot(json_path)
    experimental = read_experimental_sqlite_dashboard_snapshot(database)
    json_state, sqlite_state = authoritative.state, experimental.state
    normalized = dict(json_state)
    for section in SECTIONS:
        normalized.setdefault(section, {})
    json_inventory = build_inventory(authoritative.state)
    sqlite_inventory = build_inventory(experimental.state)
    experimental.verify_current()
    if read_json_dashboard_snapshot(json_path).state != json_state:
        raise RuntimeError("Dashboard JSON changed during parity rehearsal")
    from app.sqlite_operation_coordinator import INTENTS_KEY
    pending = INTENTS_KEY in json_state or INTENTS_KEY in sqlite_state
    states_match = normalized == sqlite_state
    inventories_match = json_inventory == sqlite_inventory
    return {"status": "matching_advisory_only" if states_match and inventories_match and not pending else "blocked",
            "state_parity": states_match, "inventory_parity": inventories_match,
            "pending_operation_present": pending,
            "sqlite_revision": experimental.revision, "storage_authority": "json",
            "production_activation": "disabled", "authorization": "not_authorized", "read_only": True}


def lifecycle_clock(value, *, limit=None, now=None):
    """Display a saved clock without guessing from folder dates or other stages.

    Naive timestamps retain their original wall-time meaning. Aware timestamps
    keep their recorded offset, including when computing removal-stage ages.
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
    """Format process observations in a known zone; never reinterpret naive clocks."""
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
    """Summarize this inventory capture without rescanning or changing dates.

    Unmatched counts refer to the named stage, not proof that media was deleted.
    Unavailable tracking/directories are unknown coverage, never zero-date claims.
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
    """Project bounded overview lists from the already enriched folder snapshot.

    Waiting uses recorded elapsed days, with title/library ties. Holding uses the
    existing estimated calendar date. Unknown clocks sort last and never acquire
    an inferred date. This function performs no collection or state writes.
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


# Presentation of scheduler records; no new Docker runtime dependency.
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


def _scan_entry(record, zone):
    """Project only known scalar fields; never pass free-text errors/payloads through."""
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
    trigger_label = {'scheduled': 'Daily schedule', 'manual': 'Manual preview' if preview is True else 'Manual request',
                     'startup': 'Startup', 'rescue': 'Manual rescue'}.get(trigger, 'Not reported') if isinstance(trigger, str) else 'Not reported'
    duration_display = 'Not recorded'
    if duration is not None:
        minutes, seconds = divmod(duration, 60)
        duration_display = f'{int(minutes)}m {seconds:g}s' if minutes else f'{seconds:g}s'
    return {'label': label, 'group': group, 'mode': mode, 'trigger': trigger_label,
        'started': observation_datetime(start.isoformat(), zone) if start else 'Not recorded',
        'finished': observation_datetime(finish.isoformat(), zone) if finish else 'Not recorded',
        'duration': duration, 'duration_display': duration_display, 'reason': reason,
        'moves_proposed': _scan_counter(record.get('moves_proposed')),
        'discovery_changes': _scan_counter(record.get('discovery_changes')),
        'moves_completed': _scan_counter(record.get('moves_completed')),
        'arr_completed': _scan_counter(record.get('arr_completed'))}


def build_scan_view(run, history, *, timezone_name=None):
    """Render passed-in observations only; no filesystem/network/history fallback."""
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
    rows = [_scan_entry(record, timezone_name) for record in history[:100] if isinstance(record, dict)] if valid_history else []
    available = valid_history and run.get('history_scope') == 'current_process' and (not history or bool(rows))
    return {'current_state': state, 'current_detail': detail, 'history_available': available,
        'history_partial': valid_history and any(not isinstance(record, dict) for record in history[:100]),
        'rows': rows if available else [], 'latest': rows[0] if available and rows else None,
        'history_scope': 'current_process', 'freshness_verified': False,
        'skipped_title_count': None, 'blocked_title_count': None}
