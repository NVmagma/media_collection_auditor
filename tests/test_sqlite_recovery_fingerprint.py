"""Pre-move fingerprints remain read-only, advisory and fail closed."""

import os

import pytest

from app.sqlite_recovery_fingerprint import (
    capture_directory_fingerprint,
    compare_directory_fingerprint,
)


def test_directory_capture_and_matching_metadata_remain_unverified(tmp_path):
    directory = tmp_path / "movie"
    directory.mkdir()
    before = capture_directory_fingerprint(str(directory))
    after = capture_directory_fingerprint(str(directory))
    assert before["status"] == "captured"
    result = compare_directory_fingerprint(before, after)
    assert result["fingerprint_binding"] == "metadata_consistent_unverified"
    assert result["authorization"] == "not_authorized"
    assert str(directory) not in str(result)
    assert "inode" not in str(result)


def test_replaced_directory_is_not_verified(tmp_path):
    directory = tmp_path / "movie"
    directory.mkdir()
    before = capture_directory_fingerprint(str(directory))
    directory.rmdir()
    directory.mkdir()
    after = capture_directory_fingerprint(str(directory))
    # Replacement can reuse an inode; neither outcome is authorization.
    result = compare_directory_fingerprint(before, after)
    assert result["authorization"] == "not_authorized"
    assert result["fingerprint_binding"] in (
        "unverified", "metadata_consistent_unverified"
    )


@pytest.mark.parametrize("value", ["relative", "/tmp/../tmp", "", None, 42])
def test_invalid_paths_never_capture(value):
    assert capture_directory_fingerprint(value)["status"] == "invalid_path"


def test_symlinked_parent_rejected(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "movie").mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    assert capture_directory_fingerprint(str(link / "movie"))["status"] == "symlink_unsafe"


def test_regular_file_is_not_directory(tmp_path):
    file = tmp_path / "movie"
    file.write_text("not media")
    assert capture_directory_fingerprint(str(file))["status"] == "not_directory"


def test_missing_path_is_not_proof(tmp_path):
    assert capture_directory_fingerprint(str(tmp_path / "missing"))["status"] == "missing"


def test_metadata_change_blocks_matching(tmp_path):
    directory = tmp_path / "movie"
    directory.mkdir()
    before = capture_directory_fingerprint(str(directory))
    after = dict(before, ctime_ns=before["ctime_ns"] + 1)
    result = compare_directory_fingerprint(before, after)
    assert result["reason"] == "fingerprint_mismatch"
    assert result["authorization"] == "not_authorized"


@pytest.mark.parametrize("invalid", [
    None, {}, {"status": "missing"}, {"status": "captured", "inode": True},
])
def test_invalid_recorded_fingerprint_blocks(invalid, tmp_path):
    directory = tmp_path / "movie"
    directory.mkdir()
    result = compare_directory_fingerprint(
        invalid, capture_directory_fingerprint(str(directory))
    )
    assert result["reason"] == "fingerprint_unavailable"
    assert result["authorization"] == "not_authorized"


def test_capture_never_opens_media_contents(monkeypatch, tmp_path):
    directory = tmp_path / "movie"
    directory.mkdir()
    def forbidden(*args, **kwargs):
        raise AssertionError("content access forbidden")
    monkeypatch.setattr("builtins.open", forbidden)
    assert capture_directory_fingerprint(str(directory))["status"] == "captured"
