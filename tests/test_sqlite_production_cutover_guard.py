"""No production activation or filesystem mutation from the cutover guard."""

from copy import deepcopy

from app.sqlite_production_cutover_guard import assess_sqlite_cutover
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS


def lab(tmp_path):
    state = {section: {} for section in SECTIONS}
    state["first_seen"]["Movie"] = "2024-01-01T00:00:00"
    db = tmp_path / "state.db"
    write_offline_snapshot(state, db)
    roots = {}
    for stage in ("transient", "holding", "removal", "keep"):
        path = tmp_path / stage
        path.mkdir()
        roots[stage] = path
    return db, state, roots


def assess(db, state, roots, **kwargs):
    return assess_sqlite_cutover(
        database=db, json_state=state, stage_roots=roots, **kwargs)


def test_parity_still_never_authorizes_cutover(tmp_path):
    db, state, roots = lab(tmp_path)
    before = db.read_bytes()
    result = assess(db, state, roots,
                    jellyfin_protection_available=True,
                    external_integrations_verified=True)
    assert result["status"] == "blocked"
    assert result["production_activation"] == "disabled"
    assert result["authorization"] == "not_authorized"
    assert result["blockers"] == ["sqlite_production_activation_not_approved"]
    assert result["read_only"] is True
    assert db.read_bytes() == before


def test_json_sqlite_mismatch_blocks(tmp_path):
    db, state, roots = lab(tmp_path)
    changed = deepcopy(state)
    changed["first_seen"]["Other"] = "2024-02-01T00:00:00"
    result = assess(db, changed, roots)
    assert "json_sqlite_state_mismatch" in result["blockers"]


def test_pending_operation_blocks_even_if_snapshots_match(tmp_path):
    db, state, roots = lab(tmp_path)
    from app.sqlite_audit_session import RevisionedAuditSession
    from app.state_store import GuardedSQLiteStateStore
    session = RevisionedAuditSession(GuardedSQLiteStateStore(db))
    session.state["sqlite_pending_operations"] = {
        "id": "pending", "kind": "move", "phase": "intent_recorded",
        "details": {"media_key": "Movie"}}
    session.checkpoint()
    result = assess(db, state, roots)
    assert "sqlite_unresolved_operations" in result["blockers"]


def test_missing_stage_and_unavailable_jellyfin_block(tmp_path):
    db, state, roots = lab(tmp_path)
    roots.pop("keep")
    result = assess(db, state, roots)
    assert "stage_roots_incomplete" in result["blockers"]
    assert "jellyfin_protection_unverified" in result["blockers"]


def test_missing_database_does_not_create_new_state(tmp_path):
    db, state, roots = lab(tmp_path)
    db.unlink()
    result = assess(db, state, roots)
    assert "sqlite_snapshot_unavailable_or_invalid" in result["blockers"]
    assert not db.exists()
