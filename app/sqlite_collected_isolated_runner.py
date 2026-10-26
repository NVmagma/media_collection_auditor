"""Jellyfin-collected, plan-bound execution for marked disposable titles only.

The supplied fetch transport must be trusted. No production CLI or activation,
automatic Arr delivery, season pruning or deletion exists here. Portable copy
staging retains its source and never promotes or reconciles the lifecycle.
"""
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from time import monotonic

from app.sqlite_collection_decision_preview import preview_collection
from app.sqlite_copy_stage_binding import TRANSITIONS
from app.sqlite_disposable_lifecycle_flow import execute_disposable_lifecycle_move
from app.sqlite_disposable_planned_executor import validate_disposable_move_candidate
from app.sqlite_guarded_move_plan import plan_guarded_moves
from app.sqlite_isolated_lifecycle_runner import isolated_runner_lock
from app.sqlite_jellyfin_collection import collect_title_observation
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_title_identity import validate_title_folder
from app.state_store import GuardedSQLiteStateStore


STAGES = {"Waiting": "transient", "Holding": "holding", "Removal": "removal", "Keep": "keep"}


def run_collected_isolated_move(**kwargs):
    """Collect and refresh protections for the isolated no-replace move flow."""
    return _run_collected_isolated_operation(_copy_stage=False, _complete_copy=False,
        _held_runner_binding=None, _expected_runner_revision=None, **kwargs)


def run_collected_isolated_copy(**kwargs):
    """Collect and refresh protections for source-retaining disposable staging.

    No promotion, source cleanup, Arr delivery or lifecycle reconciliation.
    """
    return _run_collected_isolated_operation(_copy_stage=True, _complete_copy=False,
        _held_runner_binding=None, _expected_runner_revision=None, **kwargs)


def run_collected_isolated_copy_completion(**kwargs):
    """One live-witness lab flow; quarantine original, never delete its bytes."""
    return _run_collected_isolated_operation(_copy_stage=True, _complete_copy=True,
        _held_runner_binding=None, _expected_runner_revision=None, **kwargs)


def _run_collected_isolated_operation(*, root, database, operation_id, media_key,
                                title_folder, jellyfin_type, thresholds, fetch,
                                favorites_trigger_keep=True, maximum_age_seconds=60,
                                clock=datetime.now, timer=monotonic, fault_at=None,
                                arr_sync_request=None, _copy_stage=False, _complete_copy=False, completion_fault_at=None,
                                _held_runner_binding=None, _expected_runner_revision=None):
    """Collect twice under the runner lock; require unchanged complete signals.

    Time budget covers both scans and intervening planning. This establishes a
    bounded experimental observation window, not transactional protection or
    independent production freshness. Completion alone collects two unchanged
    observations after hashing each phase; collection and metadata checks stay
    bounded, with deadlines checked before actions.
    """
    if completion_fault_at is not None and not _complete_copy:
        raise ValueError("Completion faults require the completion rehearsal")
    if completion_fault_at not in (None, "after_retirement_intent", "after_source_quarantine", "after_completion_checkpoint"):
        raise ValueError("Invalid completion fault boundary")
    thresholds = deepcopy(thresholds)
    arr_sync_request = deepcopy(arr_sync_request)
    folder = validate_title_folder(title_folder)
    expected_key = folder if jellyfin_type == "Movie" else "TV/" + folder
    if jellyfin_type not in ("Movie", "Series") or media_key != expected_key:
        raise ValueError("Jellyfin type, title folder and tracking key mismatch")
    if type(maximum_age_seconds) is not int or not 1 <= maximum_age_seconds <= 60:
        raise ValueError("Observation budget must be between 1 and 60 seconds")
    root, database = Path(root), Path(database)
    if database != root / "state.db":
        raise RuntimeError("Disposable runner database binding mismatch")
    with (isolated_runner_lock(root) if _held_runner_binding is None
          else nullcontext(_held_runner_binding)) as verify_binding:
        verify_binding()
        state, revision = GuardedSQLiteStateStore(database).load_with_revision()
        if (_expected_runner_revision is not None
                and (type(_expected_runner_revision) is not int or revision != _expected_runner_revision)):
            raise RuntimeError("Stale batch operation revision")
        if INTENTS_KEY in state:
            raise RuntimeError("Unresolved SQLite operation; collected runner stopped")
        started, tick = clock(), timer()
        if not isinstance(started, datetime) or started.tzinfo is not None:
            raise ValueError("Naive collection clock required")

        window_started, window_tick = started, tick
        last_time, last_tick = started, tick

        def sample_time():
            nonlocal last_time, last_tick
            current, current_tick = clock(), timer()
            if (not isinstance(current, datetime) or current.tzinfo is not None
                    or current < last_time or not current_tick >= last_tick):
                raise RuntimeError("Jellyfin observation window expired; replan required")
            last_time, last_tick = current, current_tick
            return current, current_tick

        def check_window():
            current, current_tick = sample_time()
            elapsed = current_tick - window_tick
            if (not isinstance(current, datetime) or current.tzinfo is not None
                    or current < window_started or (current - window_started).total_seconds() > maximum_age_seconds
                    or not 0 <= elapsed <= maximum_age_seconds):
                raise RuntimeError("Jellyfin observation window expired; replan required")

        def collect():
            result = collect_title_observation(
                fetch=fetch, jellyfin_type=jellyfin_type, folder=folder,
                media_key=media_key, now=clock())
            check_window()
            if result["status"] != "shape_valid_untrusted":
                raise RuntimeError("Complete unambiguous Jellyfin observation required")
            return result

        initial = collect()
        preview = preview_collection(
            database=database, now=started, thresholds=thresholds,
            signals_by_key={media_key: initial["signals"]},
            favorites_trigger_keep=favorites_trigger_keep)
        if preview["revision"] != revision:
            raise RuntimeError("SQLite revision changed during collection")
        plan = plan_guarded_moves(preview)
        rows = [row for row in plan["rows"] if row["media_key"] == media_key]
        if len(rows) != 1 or rows[0]["status"] != "candidate_requires_verification":
            raise RuntimeError("No collected lifecycle move candidate")
        source = STAGES[rows[0]["source_stage"]]
        destination = STAGES[rows[0]["destination_stage"]]
        bundle = {"plan": plan, "now": started, "thresholds": dict(thresholds),
                  "signals_by_key": {media_key: dict(initial["signals"])},
                  "favorites_trigger_keep": favorites_trigger_keep}
        validate_disposable_move_candidate(
            planned_move=bundle, media_key=media_key,
            source_stage=source, destination_stage=destination)

        def refresh_before_intent():
            check_window()
            current = collect()
            if current["identity"] != initial["identity"] or current["signals"] != initial["signals"]:
                raise RuntimeError("Jellyfin identity or signals changed; replan required")

        def renew_copy_window():
            nonlocal window_started, window_tick
            # Only live completion phases use this callback. No persisted
            # pending operation can enter the collected runner on restart.
            window_started, window_tick = sample_time()
            refresh_before_intent()
            refresh_before_intent()

        verify_binding()
        if _copy_stage:
            if ((source, destination) not in TRANSITIONS
                    or (not _complete_copy and source != "transient")):
                raise RuntimeError("Portable staging requires a Waiting source candidate; completion also supports Holding")
            if arr_sync_request is not None and not _complete_copy:
                raise ValueError("Copy staging cannot deliver or queue Arr requests")
            if _complete_copy and media_key in state["arr_sync_pending"]:
                raise RuntimeError("Existing Arr queue blocks copy completion")
            if _complete_copy and arr_sync_request is not None:
                from app.sqlite_arr_queue_plan import planned_arr_queue_entry
                planned_arr_queue_entry(request=arr_sync_request, media_key=media_key,
                                        title_folder=folder, destination_stage=destination)
            from app.sqlite_disposable_copy_stage import _stage_copy
            result = _stage_copy(
                root=root, operation_id=operation_id, media_key=media_key,
                title_folder=folder, persist_intent=True, planned_move=bundle,
                planned_destination=destination, fault_at=fault_at,
                _held_binding=verify_binding,
                _before_intent_review=None if _complete_copy else refresh_before_intent,
                _before_intent_check=check_window,
                _refresh_after_hash=renew_copy_window if _complete_copy else None,
                _source_stage=source)
            if not _complete_copy:
                return result
            from app.sqlite_disposable_copy_publication import _publish_disposable_copy
            return _publish_disposable_copy(root=root, _held_binding=verify_binding,
                _completion={"observed_at": started, "refresh": renew_copy_window,
                             "check_window": check_window, "arr_sync_request": deepcopy(arr_sync_request),
                             "fault_at": completion_fault_at})
        return execute_disposable_lifecycle_move(
            root=root, database=database, operation_id=operation_id, media_key=media_key,
            title_folder=folder, source_stage=source, destination_stage=destination,
            observed_at=started, planned_move=bundle, expected_revision=revision,
            fault_at=fault_at, _use_directory_handles=True,
            _verify_runner_binding=verify_binding, _before_intent_review=refresh_before_intent,
            arr_sync_request=arr_sync_request)
