"""Plan-bound named execution: detached requests, locked revalidation, no production."""
from datetime import datetime
import sys

import pytest

from app.sqlite_collection_decision_preview import preview_collection
from app.sqlite_guarded_move_plan import plan_guarded_moves
from app.sqlite_isolated_lifecycle_runner import run_isolated_planned_move
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore

NOW = datetime(2026, 1, 1)
LIMITS = {"Waiting": 7, "Holding": 7, "Removal": 7, "Keep": 0}
FOLDER = "Named Movie"


def lab(tmp_path, signals=None):
    root = tmp_path / "lab"
    root.mkdir()
    (root / ".sqlite_disposable_rehearsal").write_text("DISPOSABLE ONLY\n")
    for stage in ("transient", "holding", "removal", "keep"):
        (root / stage).mkdir()
    (root / "transient" / FOLDER).mkdir()
    (root / "transient" / FOLDER / "payload").write_text("disposable")
    state = {section: {} for section in SECTIONS}
    state["first_seen"][FOLDER] = "2024-01-01T00:00:00"
    database = root / "state.db"
    write_offline_snapshot(state, database)
    signals = {FOLDER: {}} if signals is None else signals
    limits = dict(LIMITS)
    plan = plan_guarded_moves(preview_collection(
        database=database, now=NOW, thresholds=limits, signals_by_key=signals))
    bundle = {"plan": plan, "now": NOW, "thresholds": limits, "signals_by_key": signals}
    return root, database, bundle


def run(root, database, bundle, **kwargs):
    return run_isolated_planned_move(
        root=root, database=database, operation_id="named-plan", media_key=FOLDER,
        title_folder=FOLDER, planned_move=bundle, **kwargs)


def unchanged(root, database, before):
    assert database.read_bytes() == before
    assert (root / "transient" / FOLDER / "payload").read_text() == "disposable"
    assert not (root / "holding" / FOLDER).exists()
    assert not (root / "keep" / FOLDER).exists()


@pytest.mark.parametrize("bundle", [None, {}, {"plan": {}}, {"plan": {"source_revision": True}}])
def test_missing_or_invalid_plan_is_rejected_without_writes(tmp_path, bundle):
    root, database, _ = lab(tmp_path)
    before = database.read_bytes()
    with pytest.raises(ValueError):
        run(root, database, bundle)
    unchanged(root, database, before)
    assert not (root / ".sqlite_runner.lock").exists()


def test_unplanned_destination_is_rejected(tmp_path):
    root, database, bundle = lab(tmp_path)
    before = database.read_bytes()
    with pytest.raises(RuntimeError, match="No matching"):
        run(root, database, bundle, destination_stage="keep")
    unchanged(root, database, before)


def test_different_observation_requires_replanning(tmp_path):
    root, database, bundle = lab(tmp_path)
    before = database.read_bytes()
    with pytest.raises(RuntimeError, match="replan required"):
        run(root, database, bundle, observed_at=datetime(2026, 1, 2))
    unchanged(root, database, before)


def test_stale_revision_is_rejected_under_lock(tmp_path):
    root, database, bundle = lab(tmp_path)
    store = GuardedSQLiteStateStore(database)
    state, revision = store.load_with_revision()
    state["extra"] = {"new": True}
    store.save_if_revision(state, revision)
    before = database.read_bytes()
    with pytest.raises(RuntimeError, match="Stale isolated"):
        run(root, database, bundle)
    unchanged(root, database, before)


@pytest.mark.parametrize("change", ["signals", "thresholds", "required_checks", "rows"])
def test_changed_plan_inputs_block_before_intent(tmp_path, change):
    root, database, bundle = lab(tmp_path)
    if change == "signals":
        bundle["signals_by_key"][FOLDER] = {"protected": True, "keep_all": True}
    elif change == "thresholds":
        bundle["thresholds"]["Waiting"] = 10000
    elif change == "required_checks":
        bundle["plan"]["rows"][0]["required_checks"] = []
    else:
        bundle["plan"]["rows"].append(dict(bundle["plan"]["rows"][0]))
    before = database.read_bytes()
    with pytest.raises(RuntimeError):
        run(root, database, bundle)
    unchanged(root, database, before)


def test_missing_protection_observation_cannot_plan_a_move(tmp_path):
    root, database, bundle = lab(tmp_path, signals={})
    before = database.read_bytes()
    with pytest.raises(RuntimeError, match="No matching"):
        run(root, database, bundle)
    unchanged(root, database, before)


@pytest.mark.skipif(sys.platform != "linux", reason="Atomic no-replace rename requires Linux")
@pytest.mark.parametrize("protected,target", [(False, "holding"), (True, "keep")])
def test_matching_named_plan_moves_to_only_its_candidate(tmp_path, protected, target):
    signals = {FOLDER: {"protected": True, "keep_all": True}} if protected else None
    root, database, bundle = lab(tmp_path, signals=signals)
    result = run(root, database, bundle, destination_stage=target)
    assert result["status"] == "disposable_reconciled"
    state, _ = GuardedSQLiteStateStore(database).load_with_revision()
    section = "keep_seen" if protected else "queued"
    assert state[section][FOLDER] == NOW.isoformat()
    assert FOLDER not in state["first_seen"]
    assert "sqlite_pending_operations" not in state
    assert (root / target / FOLDER / "payload").read_text() == "disposable"


def test_plan_bound_intent_is_durable_and_restart_never_replays(tmp_path):
    root, database, bundle = lab(tmp_path)
    with pytest.raises(RuntimeError, match="Injected crash after intent"):
        run(root, database, bundle, fault_at="after_intent")
    state, _ = GuardedSQLiteStateStore(database).load_with_revision()
    intent = state["sqlite_pending_operations"]
    assert intent["details"]["media_key"] == FOLDER
    assert intent["details"]["source"] == str(root / "transient" / FOLDER)
    assert intent["details"]["destination"] == str(root / "holding" / FOLDER)
    assert intent["details"]["lifecycle_clock_binding"]["observed_at"] == NOW.isoformat()
    assert FOLDER in state["first_seen"]
    before = database.read_bytes()
    with pytest.raises(RuntimeError, match="Unresolved"):
        run(root, database, bundle)
    unchanged(root, database, before)
