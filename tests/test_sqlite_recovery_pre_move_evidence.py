"""Versioned pre-move envelopes cannot authorize recovery or mutate state."""

from copy import deepcopy

import pytest

from app.sqlite_recovery_pre_move_evidence import (
    build_pre_move_evidence, validate_pre_move_evidence,
)


def test_build_and_validate_candidate_without_authorization(tmp_path):
    directory = tmp_path / "media"
    directory.mkdir()
    evidence = build_pre_move_evidence(str(directory))
    assert evidence["version"] == 1
    result = validate_pre_move_evidence(evidence)
    assert result["evidence_verification"] == "schema_valid_untrusted"
    assert result["authorization"] == "not_authorized"
    assert "inode" not in str(result)
    assert str(directory) not in str(result)


@pytest.mark.parametrize("mutation,reason", [
    (lambda e: e.update(version=2), "unsupported_evidence_version"),
    (lambda e: e.update(version=True), "unsupported_evidence_version"),
    (lambda e: e.update(source="post_move"), "invalid_evidence_source"),
    (lambda e: e.update(extra="unexpected"), "invalid_evidence_envelope"),
    (lambda e: e["fingerprint"].update(inode=True), "invalid_fingerprint"),
    (lambda e: e["fingerprint"].update(inode=-1), "invalid_fingerprint"),
    (lambda e: e["fingerprint"].update(status="missing"), "invalid_fingerprint"),
    (lambda e: e["fingerprint"].pop("ctime_ns"), "invalid_fingerprint"),
    (lambda e: e["fingerprint"].update(extra="data"), "invalid_fingerprint"),
])
def test_malformed_evidence_fails_closed(tmp_path, mutation, reason):
    directory = tmp_path / "media"
    directory.mkdir()
    evidence = deepcopy(build_pre_move_evidence(str(directory)))
    mutation(evidence)
    result = validate_pre_move_evidence(evidence)
    assert result["reason"] == reason
    assert result["authorization"] == "not_authorized"


def test_missing_or_symlink_source_cannot_build_evidence(tmp_path):
    directory = tmp_path / "media"
    directory.mkdir()
    link = tmp_path / "link"
    link.symlink_to(directory, target_is_directory=True)
    for path in (str(link), str(tmp_path / "missing")):
        with pytest.raises(RuntimeError, match="unavailable"):
            build_pre_move_evidence(path)


def test_untrusted_payload_is_not_echoed():
    result = validate_pre_move_evidence({"secret": "token"})
    assert "token" not in str(result)
    assert result["authorization"] == "not_authorized"
