"""Explicit, detached dashboard reads; production authority remains JSON."""
from dataclasses import dataclass, field
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
