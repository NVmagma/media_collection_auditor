"""Disposable Arr response checks; no network requests are made."""

import pytest

from app.sqlite_arr_reconciliation import inspect_arr_sync


def _details():
    return {
        "service": "radarr", "title_id": 42,
        "root": "/media/Movies_keep", "monitored": False,
    }


def _record():
    return {
        "id": 42, "path": "/media/Movies_keep/Movie", "monitored": False,
    }


def test_matching_record_remains_unverified():
    assert inspect_arr_sync(_details(), _record()) == "matching_record_unverified"


def test_root_mismatch_is_not_success():
    record = _record()
    record["path"] = "/media/Movies/Movie"
    assert inspect_arr_sync(_details(), record) == "root_mismatch"


def test_monitoring_mismatch_is_not_success():
    record = _record()
    record["monitored"] = True
    assert inspect_arr_sync(_details(), record) == "monitoring_mismatch"


def test_missing_and_wrong_identity_fail_closed():
    with pytest.raises(RuntimeError, match="unavailable"):
        inspect_arr_sync(_details(), None)
    record = _record()
    record["id"] = 43
    with pytest.raises(RuntimeError, match="identity mismatch"):
        inspect_arr_sync(_details(), record)


def test_invalid_expected_fields_fail_closed():
    for field, value in (
        ("service", "jellyfin"), ("title_id", True), ("title_id", 0),
        ("root", "relative"), ("root", "/media/../Movies"),
        ("monitored", "false"),
    ):
        details = _details()
        details[field] = value
        with pytest.raises(RuntimeError):
            inspect_arr_sync(details, _record())


def test_invalid_actual_fields_fail_closed():
    for field, value in (
        ("id", True), ("monitored", None), ("path", None),
        ("path", "/media/Movies_keep/../Other/Movie"),
    ):
        record = _record()
        record[field] = value
        with pytest.raises(RuntimeError):
            inspect_arr_sync(_details(), record)


def test_sonarr_record_uses_same_safety_checks():
    details = _details()
    details["service"] = "sonarr"
    details["root"] = "/media/TV_keep"
    record = _record()
    record["path"] = "/media/TV_keep/Show"
    assert inspect_arr_sync(details, record) == "matching_record_unverified"
