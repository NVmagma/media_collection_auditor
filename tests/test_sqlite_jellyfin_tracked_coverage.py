"""Coverage reconciles observations to tracked keys without mutating the lab DB."""
from datetime import datetime

import pytest

from app.sqlite_jellyfin_preview_bridge import preview_with_collected_jellyfin
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS

NOW = datetime(2026, 10, 1, 12)
LIMITS = {"Waiting": 7, "Holding": 7, "Removal": 7, "Keep": 0}


def database(tmp_path, sections):
    state = {section: {} for section in SECTIONS}
    for section, keys in sections.items():
        state[section] = {key: "2026-09-01T12:00:00" for key in keys}
    db = tmp_path / "coverage.db"
    write_offline_snapshot(state, db)
    return db


def item(identity="movie", path="/media/Movie/file.mkv", tags=None):
    return {"Id": identity, "Path": path, "Tags": tags or [],
            "UserData": {"Played": False, "PlayCount": 0, "IsFavorite": False}}


def preview(db, requests, items):
    def fetch(path, params):
        if path == "/Users":
            return [{"Id": "user"}]
        records = items[params["IncludeItemTypes"]]
        return {"TotalRecordCount": len(records), "Items": records}
    before = db.read_bytes()
    result = preview_with_collected_jellyfin(
        database=db, now=NOW, thresholds=LIMITS, requests=requests, fetch=fetch)
    assert db.read_bytes() == before
    assert result["read_only"] is True
    assert result["authorization"] == "not_authorized"
    assert result["production_activation"] == "disabled"
    assert all(row["authorization"] == "not_authorized"
               for row in result["preview"]["decisions"])
    return result


def request(folder="Movie", kind="Movie"):
    return {"folder": folder, "jellyfin_type": kind}


def test_reports_missing_requests_across_all_stages_once_per_title(tmp_path):
    db = database(tmp_path, {"first_seen": ["Movie"], "queued": ["Movie", "Held"],
                             "in_removal": ["Removed"], "keep_seen": ["TV/Kept"]})
    result = preview(db, {}, {})
    coverage = result["coverage"]
    assert coverage["tracked_titles"] == coverage["blocked_titles"] == 4
    assert coverage["covered_titles"] == 0
    assert coverage["complete"] is False
    assert all(row["blockers"] == ["jellyfin_title_request_missing"]
               for row in coverage["titles"])
    assert all(row["action"] == "none" for row in result["preview"]["decisions"])


@pytest.mark.parametrize("records,blocker", [
    ([], "jellyfin_title_unmatched"),
    ([item(), item("other", "/other/Movie/file.mkv")], "jellyfin_title_ambiguous"),
])
def test_missing_or_ambiguous_match_never_contributes_signals(tmp_path, records, blocker):
    db = database(tmp_path, {"queued": ["Movie"]})
    result = preview(db, {"Movie": request()}, {"Movie": records})
    assert result["status"] == "blocked"
    assert result["coverage"]["complete"] is False
    assert blocker in result["coverage"]["titles"][0]["blockers"]
    assert result["preview"]["decisions"][0]["action"] == "none"


def test_shared_identity_blocks_every_state_key(tmp_path):
    db = database(tmp_path, {"first_seen": ["Movie", "Alias/Movie"]})
    result = preview(db, {key: request() for key in ("Movie", "Alias/Movie")},
                     {"Movie": [item(tags=["keep-forever"])]})
    assert result["coverage"]["blocked_titles"] == 2
    assert all(row["blockers"] == ["jellyfin_identity_shared_by_state_keys"]
               for row in result["coverage"]["titles"])
    assert all(row["action"] == "none" for row in result["preview"]["decisions"])


def test_valid_protection_remains_authoritative_and_extra_requests_are_counted(tmp_path):
    db = database(tmp_path, {"queued": ["Movie"], "keep_seen": ["TV/Show"]})
    result = preview(db, {"Movie": request(), "TV/Show": request("Show", "Series"),
                          "Untracked": request("Other")}, {
        "Movie": [item(tags=["keep-forever", "not-at-all"]),
                  item("other", "/media/Other/file.mkv")],
        "Series": [item("show", "/media/TV/Show", ["keep-all-seasons"])],
    })
    assert result["status"] == "advisory_only"
    assert result["coverage"]["complete"] is True
    assert result["coverage"]["covered_titles"] == 2
    assert result["coverage"]["untracked_request_count"] == 1
    rows = {row["media_key"]: row for row in result["preview"]["decisions"]}
    assert rows["Movie"]["candidate_action"] == "rescue"
    assert rows["TV/Show"]["candidate_action"] == "none"


def test_complete_coverage_does_not_authorize_removal(tmp_path):
    db = database(tmp_path, {"in_removal": ["Movie"]})
    result = preview(db, {"Movie": request()}, {"Movie": [item()]})
    assert result["coverage"]["complete"] is True
    assert result["status"] == "blocked"
    row = result["preview"]["decisions"][0]
    assert row["action"] == "none"
    assert "deletion_not_authorized" in row["blockers"]


@pytest.mark.parametrize("identity,path", [
    ("movie", "/elsewhere/Show"),
    ("show", "/media/Movie/file.mkv"),
])
def test_shared_id_or_path_across_different_requests_blocks(tmp_path, identity, path):
    db = database(tmp_path, {"first_seen": ["Movie", "TV/" + path.rsplit("/", 1)[-1]]})
    show_key = "TV/" + path.rsplit("/", 1)[-1]
    result = preview(db, {"Movie": request(),
                          show_key: request(path.rsplit("/", 1)[-1], "Series")}, {
        "Movie": [item()], "Series": [item(identity, path)],
    })
    assert result["coverage"]["blocked_titles"] == 2
    assert result["status"] == "blocked"


def test_empty_collection_does_not_hide_unresolved_operation(tmp_path):
    state = {section: {} for section in SECTIONS}
    state["sqlite_pending_operations"] = {"unresolved": "pending"}
    db = tmp_path / "pending.db"
    write_offline_snapshot(state, db)
    result = preview(db, {}, {})
    assert result["coverage"]["complete"] is True
    assert result["preview"]["status"] == "blocked"
    assert result["status"] == "blocked"


def test_protection_counts_exclude_untracked_requests_and_include_keep_forever(tmp_path):
    db = database(tmp_path, {"queued": ["Movie"], "keep_seen": ["TV/Show"]})
    movie = item(tags=["keep-forever", "keep", "not-at-all"])
    movie["UserData"]["IsFavorite"] = True
    result = preview(db, {"Movie": request(), "TV/Show": request("Show", "Series"),
                          "Other": request("Other")}, {
        "Movie": [movie, item("other", "/media/Other/file.mkv", ["keep-forever"])],
        "Series": [item("show", "/media/Show", ["keep-all-seasons"])],
    })
    assert result["protection_summary"] == {
        "available": True,
        "counts": {"protected": 1, "keep_all": 2, "keep": 1, "favorite": 1},
    }


@pytest.mark.parametrize("requests,records", [
    ({}, {}),
    ({"Movie": request()}, {"Movie": []}),
    ({"Movie": request()}, {"Movie": [item(), item("second", "/other/Movie/f.mkv")]}),
])
def test_incomplete_coverage_never_reports_zero_protection(tmp_path, requests, records):
    db = database(tmp_path, {"queued": ["Movie"]})
    summary = preview(db, requests, records)["protection_summary"]
    assert summary["available"] is False
    assert all(value is None for value in summary["counts"].values())
