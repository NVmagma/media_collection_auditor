"""One-shot Arr delivery rehearsal for marked disposable SQLite labs only.

No HTTP client or production caller. send(details) is a trusted test transport.
Every outcome remains pending: no automatic retry, clearance or media actions.
"""
from copy import deepcopy
from pathlib import Path

from app.sqlite_arr_reconciliation import validate_arr_sync_details
from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_isolated_lifecycle_runner import isolated_runner_lock
from app.sqlite_lifecycle_checkpoint_plan import CLOCKS
from app.sqlite_operation_coordinator import INTENTS_KEY, SQLiteOperationCoordinator
from app.sqlite_title_identity import validate_title_folder
from app.state_store import GuardedSQLiteStateStore

STAGES = {"holding": "queued", "keep": "keep_seen", "removal": "in_removal"}


def deliver_isolated_arr_request(*, root, database, operation_id, media_key,
                                 title_folder, details, send, fault_at=None):
    """Persist before send; acknowledgement is not verified remote completion."""
    folder = validate_title_folder(title_folder)
    request = deepcopy(details)
    validate_arr_sync_details(request)
    if set(request) != {"service", "title_id", "root", "monitored"}:
        raise ValueError("Only non-secret Arr request fields are accepted")
    expected_key = folder if request["service"] == "radarr" else "TV/" + folder
    if media_key != expected_key or not callable(send):
        raise ValueError("Arr service/title key and transport must match")
    if fault_at not in (None, "after_intent", "after_send"):
        raise ValueError("Invalid Arr rehearsal fault boundary")
    root, database = Path(root), Path(database)
    if database != root / "state.db":
        raise RuntimeError("Disposable runner database binding mismatch")
    with isolated_runner_lock(root) as verify_binding:
        session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
        state, _ = session.read_verified_snapshot()
        if INTENTS_KEY in state:
            raise RuntimeError("Unresolved SQLite operation; Arr delivery stopped")
        queued = state["arr_sync_pending"].get(media_key)
        if (not isinstance(queued, dict) or queued.get("stage") not in STAGES
                or queued.get("root") != request["root"]
                or type(queued.get("monitored")) is not bool
                or queued["monitored"] != request["monitored"]):
            raise RuntimeError("Arr request does not match persistent queue")
        stage = queued["stage"]
        clock = STAGES[stage]
        if (media_key not in state[clock]
                or any(media_key in state[section] for section in CLOCKS.values() if section != clock)):
            raise RuntimeError("Arr destination tracking clock is missing or conflicting")
        present = []
        for name in ("transient", "holding", "removal", "keep"):
            directory = root / name
            title = directory / folder
            if directory.is_symlink() or not directory.is_dir() or title.is_symlink():
                raise RuntimeError("Unsafe Arr destination fixture")
            if title.exists():
                if not title.is_dir():
                    raise RuntimeError("Arr title fixture is not a directory")
                present.append(name)
        if present != [stage]:
            raise RuntimeError("Arr destination fixture is missing or ambiguous")
        verify_binding()
        coordinator = SQLiteOperationCoordinator(session)
        coordinator.begin(operation_id, "arr_sync", {
            **request, "media_key": media_key, "title_folder": folder, "stage": stage})
        verify_binding()
        if fault_at == "after_intent":
            raise RuntimeError("Injected Arr crash after intent")
        try:
            acknowledgement = send(deepcopy(request))
            outcome = "acknowledged_unverified" if acknowledgement is True else "unknown_response"
        except Exception:
            outcome = "request_exception_unknown"
        if fault_at == "after_send":
            raise RuntimeError("Injected Arr crash after send")
        verify_binding()
        session.read_verified_snapshot()
        intent = session.state[INTENTS_KEY]
        intent["arr_delivery_outcome"] = outcome
        if outcome == "acknowledged_unverified":
            intent["phase"] = "applied_pending_reconciliation"
        session.checkpoint()
        return {"status": "pending_verification", "outcome": outcome,
                "retry_authorized": False, "production_activation": "disabled",
                "authorization": "not_authorized"}
