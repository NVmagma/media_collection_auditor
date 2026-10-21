"""Actual dashboard inventory/health parity with no production backend switch."""
import json
import os
import sys
from pathlib import Path
import pytest

os.environ.setdefault("WEB_SESSION_SECRET", "disposable-dashboard-parity-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import web
from app.dashboard_tracking_snapshot import compare_dashboard_snapshots
from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore


def lab(tmp_path):
    media = tmp_path / "media"
    state = {section: {} for section in SECTIONS}
    for prefix, key_prefix in (("Movies", ""), ("TV", "TV/")):
        for suffix, section in (("", "first_seen"), ("_hold", "queued"),
                                ("_removal", "in_removal"), ("_keep", "keep_seen")):
            directory = media / (prefix + suffix)
            (directory / "Same Title").mkdir(parents=True)
            state[section][key_prefix + "Same Title"] = "2024-01-01T00:00:00"
    state["arr_sync_pending"]["TV/Same Title"] = {"stage": "keep", "root": "/fixture/tv_keep", "monitored": False}
    state["legacy"] = {"unknown": ["preserve"]}
    source, database = tmp_path / "state.json", tmp_path / "state.db"
    source.write_text(json.dumps(state))
    write_offline_snapshot(state, database)
    config = {"MEDIA_PATH": str(media), "ENABLE_MOVIES": "true", "ENABLE_TV": "true"}
    def build(value):
        stages, warnings = web.filesystem_stages(value, config)
        health = web.collection_health(value, stages, warnings, config)
        return {"stages": stages, "warnings": warnings, "health": health}
    return source, database, build


def test_movie_and_tv_inventory_health_match_without_writes(tmp_path):
    source, database, build = lab(tmp_path)
    before = source.read_bytes(), database.read_bytes()
    report = compare_dashboard_snapshots(json_path=source, database=database, build_inventory=build)
    assert report["state_parity"] and report["inventory_parity"]
    assert report["storage_authority"] == "json" and report["sqlite_revision"] == 0
    assert report["authorization"] == "not_authorized"
    assert (source.read_bytes(), database.read_bytes()) == before
    assert "Same Title" not in json.dumps(report) and str(tmp_path) not in json.dumps(report)


def test_advanced_sqlite_never_replaces_authoritative_json(tmp_path):
    source, database, build = lab(tmp_path)
    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    session.state["first_seen"]["New Title"] = "2024-01-01T00:00:00"
    session.checkpoint()
    report = compare_dashboard_snapshots(json_path=source, database=database, build_inventory=build)
    assert report["status"] == "blocked" and not report["state_parity"]
    assert report["storage_authority"] == "json"


@pytest.mark.parametrize("change", ["sqlite", "json"])
def test_concurrent_tracking_change_rejects_parity_report(tmp_path, change):
    source, database, build = lab(tmp_path)
    calls = 0
    def changing(value):
        nonlocal calls
        calls += 1
        if calls == 2:
            if change == "sqlite":
                other = RevisionedAuditSession(GuardedSQLiteStateStore(database))
                other.checkpoint()
            else:
                source.write_text("{}")
        return build(value)
    with pytest.raises(RuntimeError, match="session is stale|JSON changed"):
        compare_dashboard_snapshots(json_path=source, database=database, build_inventory=changing)


def test_builder_mutation_cannot_modify_captured_source(tmp_path):
    source, database, _ = lab(tmp_path)
    before = source.read_bytes(), database.read_bytes()
    def mutate(value):
        value.clear()
        return {}
    report = compare_dashboard_snapshots(json_path=source, database=database, build_inventory=mutate)
    assert report["state_parity"]
    assert (source.read_bytes(), database.read_bytes()) == before


def test_pending_operation_prevents_matching_readiness_status(tmp_path):
    source, database, build = lab(tmp_path)
    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    session.state["sqlite_pending_operations"] = {"kind": "copy_stage", "id": "pending"}
    session.checkpoint()
    source.write_text(json.dumps(session.state))
    report = compare_dashboard_snapshots(json_path=source, database=database, build_inventory=build)
    assert report["state_parity"] and report["inventory_parity"]
    assert report["pending_operation_present"] and report["status"] == "blocked"
