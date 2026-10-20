"""Readback never clears unknown delivery, retries, or loses newer state."""
from datetime import datetime, timezone, timedelta
import json
import pytest
from tests.test_sqlite_isolated_arr_runner import lab, run, KEY, DETAILS
from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_isolated_arr_inspection import inspect_isolated_arr_outcome
from app.state_store import GuardedSQLiteStateStore

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def prepare(tmp_path):
    root, database = lab(tmp_path)
    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    session.state["arr_sync_pending"][KEY].update(service="radarr", title_id=42)
    session.checkpoint()
    run(root, database, lambda request: True)
    return root, database


def record(**updates):
    value = {"id": 42, "path": "/arr/keep/" + KEY, "monitored": False}
    value.update(updates)
    return value


def envelope(value):
    return {"service": "radarr", "title_id": "42", "observed_at": NOW, "data": value}


def inspect(root, fetch, **kwargs):
    return inspect_isolated_arr_outcome(root=root, fetch=fetch, clock=lambda: NOW, **kwargs)


def test_two_matching_reads_leave_everything_pending(tmp_path):
    root, database = prepare(tmp_path)
    before = database.read_bytes()
    calls = []
    def fetch(service, title_id):
        calls.append((service, title_id))
        return envelope(record())
    report = inspect(root, fetch)
    assert calls == [("radarr", 42), ("radarr", 42)]
    assert report["observation"] == "matching_record_unverified"
    assert report["status"] == "blocked" and not report["clearance_authorized"]
    assert not report["retry_authorized"] and database.read_bytes() == before
    assert KEY not in json.dumps(report) and "/arr" not in json.dumps(report)


@pytest.mark.parametrize("remote,expected", [
    (record(id=99), "readback_unavailable_or_invalid"),
    (record(monitored=0), "readback_unavailable_or_invalid"),
    (record(monitored=True), "monitoring_mismatch"),
    (record(path="/other/" + KEY), "root_mismatch"),
    (record(path="/arr/keep/Another Title"), "title_path_mismatch")])
def test_nonmatching_readbacks_remain_blocked(tmp_path, remote, expected):
    root, database = prepare(tmp_path)
    before = database.read_bytes()
    assert inspect(root, lambda *args: envelope(remote))["observation"] == expected
    assert database.read_bytes() == before


def test_changed_second_record_is_not_treated_as_success(tmp_path):
    root, _ = prepare(tmp_path)
    reads = iter([record(), record(monitored=True)])
    assert inspect(root, lambda *args: envelope(next(reads)))["observation"] == "remote_record_changed"


@pytest.mark.parametrize("change", ["service", "future", "stale", "exception"])
def test_untrusted_or_failed_observations_are_redacted(tmp_path, change):
    root, database = prepare(tmp_path)
    before = database.read_bytes()
    def fetch(*args):
        value = envelope(record())
        if change == "service":
            value["service"] = "sonarr"
        elif change == "future":
            value["observed_at"] += timedelta(seconds=1)
        elif change == "stale":
            value["observed_at"] -= timedelta(seconds=31)
        else:
            raise RuntimeError("private token and URL")
        return value
    report = inspect(root, fetch)
    assert report["observation"] == "readback_unavailable_or_invalid"
    assert "private" not in json.dumps(report) and database.read_bytes() == before


def test_queue_identity_mismatch_blocks_before_network(tmp_path):
    root, database = prepare(tmp_path)
    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    session.state["arr_sync_pending"][KEY]["title_id"] = 99
    session.checkpoint()
    with pytest.raises(RuntimeError, match="binding invalid"):
        inspect(root, lambda *args: pytest.fail("invalid queue must precede network"))


def test_concurrent_checkpoint_rejects_report(tmp_path):
    root, database = prepare(tmp_path)
    def fetch(*args):
        other = RevisionedAuditSession(GuardedSQLiteStateStore(database))
        other.checkpoint()
        return envelope(record())
    with pytest.raises(RuntimeError, match="session is stale"):
        inspect(root, fetch)


def test_destination_replacement_rejects_report(tmp_path):
    root, _ = prepare(tmp_path)
    replaced = False
    def fetch(*args):
        nonlocal replaced
        if not replaced:
            replaced = True
            (root / "keep" / KEY).rename(root / "retained-title")
            (root / "keep" / KEY).mkdir()
        return envelope(record())
    with pytest.raises(RuntimeError, match="changed during"):
        inspect(root, fetch)


@pytest.mark.parametrize("ticks", [[0, 31], [0, 0, 0, 31], [0, -1]])
def test_expired_or_reversed_timer_never_reports_matching(tmp_path, ticks):
    root, database = prepare(tmp_path)
    before = database.read_bytes()
    values = iter(ticks)
    report = inspect(root, lambda *args: envelope(record()), timer=lambda: next(values))
    assert report["observation"] == "readback_unavailable_or_invalid"
    assert database.read_bytes() == before


def test_unknown_delivery_outcome_is_not_retried_or_cleared(tmp_path):
    root, database = prepare(tmp_path)
    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    session.state["sqlite_pending_operations"]["phase"] = "intent_recorded"
    session.state["sqlite_pending_operations"]["arr_delivery_outcome"] = "request_exception_unknown"
    session.checkpoint()
    before = database.read_bytes()
    report = inspect(root, lambda *args: envelope(record()))
    assert report["observation"] == "matching_record_unverified"
    assert not report["clearance_authorized"] and database.read_bytes() == before
