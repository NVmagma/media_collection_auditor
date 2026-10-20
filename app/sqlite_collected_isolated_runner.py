"""Jellyfin-collected, plan-bound execution for marked disposable titles only.

The supplied fetch transport must be trusted. No production CLI or activation,
Arr notifications, season pruning, cross-device copying or deletion exists here.
"""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from time import monotonic

from app.sqlite_collection_decision_preview import preview_collection
from app.sqlite_disposable_lifecycle_flow import execute_disposable_lifecycle_move
from app.sqlite_disposable_planned_executor import validate_disposable_move_candidate
from app.sqlite_guarded_move_plan import plan_guarded_moves
from app.sqlite_isolated_lifecycle_runner import isolated_runner_lock
from app.sqlite_jellyfin_collection import collect_title_observation
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_title_identity import validate_title_folder
from app.state_store import GuardedSQLiteStateStore


STAGES = {"Waiting": "transient", "Holding": "holding", "Removal": "removal", "Keep": "keep"}


def run_collected_isolated_move(*, root, database, operation_id, media_key,
                                title_folder, jellyfin_type, thresholds, fetch,
                                favorites_trigger_keep=True, maximum_age_seconds=60,
                                clock=datetime.now, timer=monotonic, fault_at=None):
    """Collect twice under the runner lock; require unchanged complete signals.

    Time budget covers both scans and intervening planning. This establishes a
    bounded experimental observation window, not transactional protection or
    independent production freshness. Expiry/change requires a new invocation.
    """
    thresholds = deepcopy(thresholds)
    folder = validate_title_folder(title_folder)
    expected_key = folder if jellyfin_type == "Movie" else "TV/" + folder
    if jellyfin_type not in ("Movie", "Series") or media_key != expected_key:
        raise ValueError("Jellyfin type, title folder and tracking key mismatch")
    if type(maximum_age_seconds) is not int or not 1 <= maximum_age_seconds <= 60:
        raise ValueError("Observation budget must be between 1 and 60 seconds")
    root, database = Path(root), Path(database)
    if database != root / "state.db":
        raise RuntimeError("Disposable runner database binding mismatch")
    with isolated_runner_lock(root) as verify_binding:
        state, revision = GuardedSQLiteStateStore(database).load_with_revision()
        if INTENTS_KEY in state:
            raise RuntimeError("Unresolved SQLite operation; collected runner stopped")
        started, tick = clock(), timer()
        if not isinstance(started, datetime) or started.tzinfo is not None:
            raise ValueError("Naive collection clock required")

        def check_window():
            elapsed = timer() - tick
            current = clock()
            if (not isinstance(current, datetime) or current.tzinfo is not None
                    or current < started or (current - started).total_seconds() > maximum_age_seconds
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

        verify_binding()
        return execute_disposable_lifecycle_move(
            root=root, database=database, operation_id=operation_id, media_key=media_key,
            title_folder=folder, source_stage=source, destination_stage=destination,
            observed_at=started, planned_move=bundle, expected_revision=revision,
            fault_at=fault_at, _use_directory_handles=True,
            _verify_runner_binding=verify_binding, _before_intent_review=refresh_before_intent)
