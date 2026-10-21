"""Bounded, fail-stop copy completion batch for explicitly marked labs only.

No production caller, retry, service delivery, cleanup or deletion. The cap
counts every attempted title, including Keep candidates, more conservatively
than the production JSON hold/delete/prune cap. It is local to this invocation.
"""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from time import monotonic

from app.sqlite_arr_queue_plan import planned_arr_queue_entry
from app.sqlite_collected_isolated_runner import _run_collected_isolated_operation
from app.sqlite_isolated_lifecycle_runner import isolated_runner_lock
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_title_identity import validate_title_folder
from app.state_store import GuardedSQLiteStateStore


def run_isolated_copy_batch(*, root, database, jobs, expected_revision,
                            max_actions_per_run, thresholds, fetch,
                            favorites_trigger_keep=True, maximum_age_seconds=60,
                            clock=datetime.now, timer=monotonic):
    """Validate the entire selection, attempt at most cap titles, halt on error.

    Completed earlier titles stay committed. A failing title may already have
    committed before an exception: report uncertainty, never retry or infer its
    outcome from counters. Any unresolved intent blocks a new invocation.
    """
    jobs, thresholds = deepcopy(jobs), deepcopy(thresholds)
    if (type(max_actions_per_run) is not int or max_actions_per_run < 0
            or type(expected_revision) is not int or expected_revision < 0):
        raise ValueError("Nonnegative integer cap and expected revision required")
    if (not isinstance(jobs, list) or not callable(fetch)
            or type(favorites_trigger_keep) is not bool
            or type(maximum_age_seconds) is not int or not 1 <= maximum_age_seconds <= 60):
        raise ValueError("Explicit jobs, trusted transport and valid collection settings required")
    if (not isinstance(thresholds, dict) or set(thresholds) != {"Waiting", "Holding", "Removal", "Keep"}
            or any(type(value) is not int or value < 0 for value in thresholds.values())):
        raise ValueError("All nonnegative lifecycle thresholds required")
    keys, operations, folders = set(), set(), set()
    required = {"operation_id", "media_key", "title_folder", "jellyfin_type"}
    for job in jobs:
        if not isinstance(job, dict) or not required <= set(job) <= required | {"arr_sync_request"}:
            raise ValueError("Explicit title job fields required")
        folder = validate_title_folder(job["title_folder"])
        operation = validate_title_folder(job["operation_id"])
        kind = job["jellyfin_type"]
        key = folder if kind == "Movie" else "TV/" + folder
        if kind not in ("Movie", "Series") or job["media_key"] != key:
            raise ValueError("Batch title identity mismatch")
        if key in keys or operation in operations or folder in folders:
            raise ValueError("Duplicate batch title or operation")
        keys.add(key)
        folders.add(folder)
        operations.add(operation)
        if job.get("arr_sync_request") is not None:
            # Validate request shape/title only. The single-title runner binds
            # the actual planned destination again before creating an intent.
            planned_arr_queue_entry(request=job["arr_sync_request"], media_key=key,
                                    title_folder=folder, destination_stage="holding")
    root, database = Path(root), Path(database)
    if database != root / "state.db":
        raise RuntimeError("Disposable batch database binding mismatch")
    with isolated_runner_lock(root) as verify_binding:
        state, revision = GuardedSQLiteStateStore(database).load_with_revision()
        if INTENTS_KEY in state:
            raise RuntimeError("Unresolved SQLite operation; batch stopped")
        if revision != expected_revision:
            raise RuntimeError("Stale batch selection revision")
        retained = state.get("sqlite_retained_sources", {})
        if not isinstance(retained, dict) or operations.intersection(retained):
            raise RuntimeError("Retained source operation already recorded or invalid")
        for key in keys:
            if (key not in state["first_seen"] or key in state["arr_sync_pending"]
                    or any(key in state[section] for section in ("queued", "in_removal", "keep_seen"))):
                raise RuntimeError("Batch requires unambiguous Waiting clocks and no queued Arr work")
        report = {"status": "cap_reached" if len(jobs) > max_actions_per_run else "completed",
                  "selected_titles": len(jobs), "attempted_titles": 0,
                  "confirmed_completed_titles": 0, "unattempted_titles": len(jobs),
                  "max_actions_per_run": max_actions_per_run,
                  "stopped_on_failure": False, "last_attempt_outcome_unverified": False,
                  "retry_authorized": False, "production_activation": "disabled",
                  "permanent_deletion_performed": False, "read_only": False}
        next_revision = revision
        for job in jobs[:max_actions_per_run]:
            report["attempted_titles"] += 1
            report["unattempted_titles"] -= 1
            try:
                verify_binding()
                result = _run_collected_isolated_operation(
                    root=root, database=database, **job, thresholds=thresholds, fetch=fetch,
                    favorites_trigger_keep=favorites_trigger_keep,
                    maximum_age_seconds=maximum_age_seconds, clock=clock, timer=timer,
                    _copy_stage=True, _complete_copy=True, _held_runner_binding=verify_binding,
                    _expected_runner_revision=next_revision)
                verify_binding()
                if (result.get("status") != "disposable_copy_reconciled_source_quarantined"
                        or result.get("lifecycle_committed") is not True
                        or result.get("original_bytes_retained") is not True
                        or type(result.get("revision")) is not int or result["revision"] <= next_revision):
                    raise RuntimeError("Unconfirmed batch operation outcome")
            except Exception:
                # Do not serialize exception text, paths, title identities or
                # service details. A failed checkpoint can already be committed.
                report.update(status="blocked", stopped_on_failure=True,
                              last_attempt_outcome_unverified=True)
                return report
            next_revision = result["revision"]
            report["confirmed_completed_titles"] += 1
        return report
