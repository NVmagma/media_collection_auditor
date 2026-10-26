"""Executable rehearsal operates only on disposable temporary fixtures."""
import pytest

from scripts.sqlite_disposable_rehearsal import (
    DIGEST, PAYLOAD, applied, inspect, move, prepare,
)
from scripts.sqlite_lab_fixture_guard import FIXTURE_NAMES


def test_disposable_lab_phases_preserve_blocked_intent(tmp_path):
    assert prepare(tmp_path)["phase"] == "intent_recorded"
    assert inspect(tmp_path)["source"] == "digest_matches_unverified"
    result = move(tmp_path)
    assert result["source"] == "missing"
    assert result["destination"] == "digest_matches_unverified"
    assert result["authorization"] == "not_authorized"
    with pytest.raises(RuntimeError, match="Unsafe or already-attempted"):
        move(tmp_path)
    assert applied(tmp_path)["phase"] == "applied_pending_reconciliation"
    assert inspect(tmp_path)["storage_authority"] == "json"
    assert (tmp_path / FIXTURE_NAMES[1]).read_bytes() == PAYLOAD


def test_disposable_lab_refuses_occupied_destination_without_overwrite(tmp_path):
    prepare(tmp_path)
    destination = tmp_path / FIXTURE_NAMES[1]
    destination.write_bytes(b"unrelated")
    with pytest.raises(RuntimeError, match="Unsafe or already-attempted"):
        move(tmp_path)
    assert destination.read_bytes() == b"unrelated"
    assert (tmp_path / FIXTURE_NAMES[0]).read_bytes() == PAYLOAD


def test_disposable_lab_refuses_ambiguous_missing_source(tmp_path):
    prepare(tmp_path)
    (tmp_path / FIXTURE_NAMES[0]).unlink()
    with pytest.raises(RuntimeError, match="Unsafe or already-attempted"):
        move(tmp_path)
    assert inspect(tmp_path)["authorization"] == "not_authorized"


def test_disposable_lab_does_not_overwrite_existing_fixture(tmp_path):
    (tmp_path / FIXTURE_NAMES[0]).write_bytes(b"important")
    with pytest.raises(RuntimeError, match="occupied"):
        prepare(tmp_path)
    assert (tmp_path / FIXTURE_NAMES[0]).read_bytes() == b"important"
