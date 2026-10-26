"""Bound, read-only Arr outcome inspection; never retry or clear an intent."""
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from time import monotonic

from app.sqlite_arr_reconciliation import inspect_arr_sync, validate_arr_sync_details
from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_fetched_recovery import _fresh_response
from app.sqlite_isolated_lifecycle_runner import isolated_runner_lock
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_title_identity import validate_title_folder
from app.state_store import GuardedSQLiteStateStore

CLOCKS = {"holding": "queued", "keep": "keep_seen", "removal": "in_removal"}


def _utc_now():
    return datetime.now(timezone.utc)


def inspect_isolated_arr_outcome(*, root, fetch, clock=_utc_now, timer=monotonic,
                                 maximum_age_seconds=30):
    """Fetch twice using a trusted authenticated GET adapter: fetch(service,id).

    Responses use the existing service/title_id/observed_at/data envelope. Even
    matching reads cannot prove which earlier request caused remote state or
    establish transactional protection freshness. All outcomes stay pending.
    """
    if not callable(fetch) or type(maximum_age_seconds) is not int or not 1 <= maximum_age_seconds <= 30:
        raise ValueError("Trusted fetch and 1-30 second observation budget required")
    root = Path(root)
    with isolated_runner_lock(root) as verify_binding:
        session = RevisionedAuditSession(GuardedSQLiteStateStore(root / "state.db"))
        state, revision = session.read_verified_snapshot()
        pending = state.get(INTENTS_KEY)
        if (not isinstance(pending, dict) or pending.get("kind") != "arr_sync"
                or pending.get("phase") not in ("intent_recorded", "applied_pending_reconciliation")
                or not isinstance(pending.get("details"), dict)):
            raise RuntimeError("Pending Arr operation required")
        details = pending["details"]
        request = {field: details.get(field) for field in ("service", "title_id", "root", "monitored")}
        validate_arr_sync_details(request)
        folder = validate_title_folder(details.get("title_folder"))
        key = folder if request["service"] == "radarr" else "TV/" + folder
        stage = details.get("stage")
        queued = state["arr_sync_pending"].get(key)
        if (details.get("media_key") != key or stage not in CLOCKS
                or not isinstance(queued, dict) or queued.get("stage") != stage
                or any(type(queued.get(field)) is not type(value) or queued.get(field) != value
                       for field, value in request.items())
                or key not in state[CLOCKS[stage]]
                or any(key in state[section] for section in ("first_seen", "queued", "in_removal", "keep_seen")
                       if section != CLOCKS[stage])):
            raise RuntimeError("Arr queue identity or clock binding invalid")

        def local_identity():
            present = []
            for name in ("transient", "holding", "keep", "removal"):
                parent = root / name
                title = parent / folder
                if parent.is_symlink() or not parent.is_dir() or title.is_symlink():
                    raise RuntimeError("Arr local destination binding invalid")
                if title.exists():
                    if not title.is_dir() or title.resolve() != title:
                        raise RuntimeError("Arr local destination binding invalid")
                    observed = title.stat()
                    parent_stat = parent.stat()
                    present.append((name, parent_stat.st_dev, parent_stat.st_ino, observed.st_dev, observed.st_ino))
            if len(present) != 1 or present[0][0] != stage:
                raise RuntimeError("Arr local destination ambiguous")
            return present[0]

        identity = local_identity()
        started, tick = clock(), timer()
        if not isinstance(started, datetime) or started.tzinfo is None:
            raise ValueError("Aware Arr inspection clock required")

        def window():
            now, elapsed = clock(), timer() - tick
            if (not isinstance(now, datetime) or now.tzinfo is None or now < started
                    or (now - started).total_seconds() > maximum_age_seconds
                    or not 0 <= elapsed <= maximum_age_seconds):
                raise RuntimeError("Arr readback observation window expired")
            return now

        observation = "readback_unavailable_or_invalid"
        try:
            observations = []
            for _ in range(2):
                envelope = fetch(request["service"], request["title_id"])
                record = _fresh_response(envelope, service=request["service"], title_id=str(request["title_id"]),
                                         now=window(), max_age=timedelta(seconds=maximum_age_seconds))
                result = inspect_arr_sync(request, record)
                if PurePosixPath(record["path"]).name != folder:
                    result = "title_path_mismatch"
                observations.append((result, record["id"], record["path"], record["monitored"]))
            window()
            observation = observations[0][0] if observations[0] == observations[1] else "remote_record_changed"
        except Exception:
            # Never expose transport exceptions, credentials, URLs or remote bodies.
            observation = "readback_unavailable_or_invalid"
        verify_binding()
        session.read_verified_snapshot()
        if local_identity() != identity:
            raise RuntimeError("Arr local destination changed during readback")
        return {"status": "blocked", "observation": observation, "revision": revision,
                "read_only": True, "retry_authorized": False, "clearance_authorized": False,
                "authorization": "not_authorized", "production_activation": "disabled",
                "storage_authority": "json"}
