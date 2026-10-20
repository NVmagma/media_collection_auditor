"""No real Arr requests: disposable queue, one-shot fake send, durable uncertainty."""
import pytest

from app.sqlite_isolated_arr_runner import deliver_isolated_arr_request
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore

KEY = "Movie A"
DETAILS = {"service": "radarr", "title_id": 42, "root": "/arr/keep", "monitored": False}


def lab(tmp_path):
    root = tmp_path / "lab"
    root.mkdir()
    (root / ".sqlite_disposable_rehearsal").write_text("DISPOSABLE ONLY\n")
    for stage in ("transient", "holding", "removal", "keep"):
        (root / stage).mkdir()
    (root / "keep" / KEY).mkdir()
    state = {section: {} for section in SECTIONS}
    state["keep_seen"][KEY] = "2024-01-01T00:00:00"
    state["arr_sync_pending"][KEY] = {"stage": "keep", "root": "/arr/keep", "monitored": False}
    database = root / "state.db"
    write_offline_snapshot(state, database)
    return root, database


def run(root, database, send, **kwargs):
    return deliver_isolated_arr_request(
        root=root, database=database, operation_id="arr-one", media_key=KEY,
        title_folder=KEY, details=DETAILS, send=send, **kwargs)


@pytest.mark.parametrize("response,outcome,phase", [
    (True, "acknowledged_unverified", "applied_pending_reconciliation"),
    (False, "unknown_response", "intent_recorded"),
    (None, "unknown_response", "intent_recorded"),
    (1, "unknown_response", "intent_recorded"),
])
def test_durable_intent_before_send_and_no_outcome_is_replayed(tmp_path, response, outcome, phase):
    root, database = lab(tmp_path)
    calls = []
    def send(request):
        state, _ = GuardedSQLiteStateStore(database).load_with_revision()
        intent = state["sqlite_pending_operations"]
        assert intent["kind"] == "arr_sync"
        assert intent["phase"] == "intent_recorded"
        assert intent["details"]["title_id"] == 42
        calls.append(request)
        request["title_id"] = 99
        return response
    result = run(root, database, send)
    assert result["outcome"] == outcome
    assert result["retry_authorized"] is False
    state, _ = GuardedSQLiteStateStore(database).load_with_revision()
    intent = state["sqlite_pending_operations"]
    assert intent["phase"] == phase
    assert intent["details"]["title_id"] == 42
    assert intent["arr_delivery_outcome"] == outcome
    assert KEY in state["arr_sync_pending"]
    assert state["keep_seen"][KEY] == "2024-01-01T00:00:00"
    before = database.read_bytes()
    with pytest.raises(RuntimeError, match="Unresolved"):
        run(root, database, send)
    assert len(calls) == 1
    assert database.read_bytes() == before


def test_exception_after_remote_acceptance_is_unknown_and_sanitized(tmp_path):
    root, database = lab(tmp_path)
    calls = []
    def send(request):
        calls.append(request)
        raise TimeoutError("secret-token private-url")
    result = run(root, database, send)
    assert result["outcome"] == "request_exception_unknown"
    assert "secret-token" not in str(result)
    state, _ = GuardedSQLiteStateStore(database).load_with_revision()
    assert state["sqlite_pending_operations"]["phase"] == "intent_recorded"
    assert "secret-token" not in str(state)
    assert len(calls) == 1


@pytest.mark.parametrize("fault,calls_expected", [("after_intent", 0), ("after_send", 1)])
def test_crash_never_causes_automatic_retry(tmp_path, fault, calls_expected):
    root, database = lab(tmp_path)
    calls = []
    with pytest.raises(RuntimeError, match="Injected Arr crash"):
        run(root, database, lambda request: calls.append(request), fault_at=fault)
    assert len(calls) == calls_expected
    before = database.read_bytes()
    with pytest.raises(RuntimeError, match="Unresolved"):
        run(root, database, lambda request: pytest.fail("no replay"))
    assert database.read_bytes() == before


@pytest.mark.parametrize("change", ["queue_root", "queue_monitoring", "missing_clock", "duplicate_location"])
def test_destination_and_queue_must_match_before_send(tmp_path, change):
    root, database = lab(tmp_path)
    store = GuardedSQLiteStateStore(database)
    state, revision = store.load_with_revision()
    if change == "queue_root":
        state["arr_sync_pending"][KEY]["root"] = "/arr/other"
    elif change == "queue_monitoring":
        state["arr_sync_pending"][KEY]["monitored"] = True
    elif change == "missing_clock":
        state["keep_seen"].clear()
    else:
        (root / "holding" / KEY).mkdir()
    store.save_if_revision(state, revision)
    before = database.read_bytes()
    with pytest.raises(RuntimeError):
        run(root, database, lambda request: pytest.fail("send must not run"))
    assert database.read_bytes() == before


def test_failed_intent_checkpoint_prevents_send(tmp_path, monkeypatch):
    root, database = lab(tmp_path)
    before = database.read_bytes()
    def fail(*args, **kwargs):
        raise RuntimeError("checkpoint failed")
    monkeypatch.setattr(GuardedSQLiteStateStore, "save_if_revision", fail)
    with pytest.raises(RuntimeError, match="checkpoint failed"):
        run(root, database, lambda request: pytest.fail("send must not run"))
    assert database.read_bytes() == before


@pytest.mark.parametrize("commit_before_error", [False, True])
def test_uncertain_outcome_checkpoint_never_replays_send(tmp_path, monkeypatch, commit_before_error):
    root, database = lab(tmp_path)
    original_save = GuardedSQLiteStateStore.save_if_revision
    writes = 0
    calls = []
    def uncertain_save(self, state, revision):
        nonlocal writes
        writes += 1
        if writes == 2:
            if commit_before_error:
                original_save(self, state, revision)
            raise RuntimeError("uncertain checkpoint")
        return original_save(self, state, revision)
    monkeypatch.setattr(GuardedSQLiteStateStore, "save_if_revision", uncertain_save)
    with pytest.raises(RuntimeError, match="uncertain checkpoint"):
        run(root, database, lambda request: calls.append(request) or True)
    state, _ = GuardedSQLiteStateStore(database).load_with_revision()
    assert "sqlite_pending_operations" in state
    assert KEY in state["arr_sync_pending"]
    before = database.read_bytes()
    with pytest.raises(RuntimeError, match="Unresolved"):
        run(root, database, lambda request: pytest.fail("no replay"))
    assert len(calls) == 1
    assert database.read_bytes() == before


def test_secret_or_unexpected_request_fields_are_not_persisted(tmp_path):
    root, database = lab(tmp_path)
    before = database.read_bytes()
    with pytest.raises(ValueError, match="non-secret"):
        deliver_isolated_arr_request(
            root=root, database=database, operation_id="arr-one", media_key=KEY,
            title_folder=KEY, details={**DETAILS, "api_key": "private-token"},
            send=lambda request: pytest.fail("send must not run"))
    assert database.read_bytes() == before


def test_stable_arr_id_in_queue_cannot_be_substituted(tmp_path):
    root, database = lab(tmp_path)
    store = GuardedSQLiteStateStore(database)
    state, revision = store.load_with_revision()
    state["arr_sync_pending"][KEY].update({"service": "radarr", "title_id": 99})
    store.save_if_revision(state, revision)
    before = database.read_bytes()
    with pytest.raises(RuntimeError, match="stable identity"):
        run(root, database, lambda request: pytest.fail("send must not run"))
    assert database.read_bytes() == before
