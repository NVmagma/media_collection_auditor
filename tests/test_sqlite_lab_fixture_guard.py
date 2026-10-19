"""Guard tests do not mount or mutate media."""
import pytest

from scripts.sqlite_lab_fixture_guard import (
    FIXTURE_NAMES, validate_disposable_lab, validate_fixture_slot,
)


def test_fixture_names_are_fixed_and_disposable():
    assert len(FIXTURE_NAMES) == len(set(FIXTURE_NAMES))
    assert all(name.startswith("sqlite_disposable_move_") for name in FIXTURE_NAMES)


def test_reject_non_lab_directory(tmp_path):
    with pytest.raises(RuntimeError, match="Dedicated /lab mount required"):
        validate_disposable_lab(tmp_path)


def test_reject_relative_directory():
    from pathlib import Path
    with pytest.raises(RuntimeError, match="Dedicated /lab"):
        validate_disposable_lab(Path("lab"))


@pytest.mark.parametrize("name", ["unexpected", "../outside", "sqlite_disposable_move_source.bin/child"])
def test_reject_unexpected_fixture_paths(tmp_path, name):
    with pytest.raises(RuntimeError, match="Unexpected fixture path"):
        validate_fixture_slot(tmp_path / name, tmp_path)


def test_existing_file_and_symlink_are_refused(tmp_path):
    source = tmp_path / FIXTURE_NAMES[0]
    source.write_bytes(b"disposable")
    with pytest.raises(RuntimeError, match="already occupied"):
        validate_fixture_slot(source, tmp_path)
    source.unlink()
    source.symlink_to(tmp_path / "missing")
    with pytest.raises(RuntimeError, match="already occupied"):
        validate_fixture_slot(source, tmp_path)


def test_missing_expected_slot_is_allowed_without_creation(tmp_path):
    source = tmp_path / FIXTURE_NAMES[0]
    validate_fixture_slot(source, tmp_path)
    assert not source.exists()


def test_inspect_disposable_fixture_is_read_only(tmp_path):
    from scripts.sqlite_lab_fixture_guard import inspect_disposable_fixture
    source = tmp_path / FIXTURE_NAMES[0]
    source.write_bytes(b"disposable-only")
    before = source.stat()
    result = inspect_disposable_fixture(source, tmp_path)
    assert result == {
        "status": "observed_unverified", "reason": "local_metadata_only",
    }
    assert source.read_bytes() == b"disposable-only"
    assert source.stat().st_mtime_ns == before.st_mtime_ns


def test_inspect_refuses_symlink_directory_and_hardlink(tmp_path):
    import os
    from scripts.sqlite_lab_fixture_guard import inspect_disposable_fixture
    source = tmp_path / FIXTURE_NAMES[0]
    source.symlink_to(tmp_path / "missing")
    assert inspect_disposable_fixture(source, tmp_path)["status"] == "blocked"
    source.unlink()
    source.mkdir()
    assert inspect_disposable_fixture(source, tmp_path)["status"] == "blocked"
    source.rmdir()
    source.write_bytes(b"disposable")
    other = tmp_path / "hardlink"
    os.link(source, other)
    assert inspect_disposable_fixture(source, tmp_path)["status"] == "blocked"


def test_inspect_refuses_missing_and_unexpected_fixture(tmp_path):
    from scripts.sqlite_lab_fixture_guard import inspect_disposable_fixture
    source = tmp_path / FIXTURE_NAMES[0]
    assert inspect_disposable_fixture(source, tmp_path)["reason"] == "fixture_unavailable"
    other = tmp_path / "production_movie"
    other.write_bytes(b"untouched")
    assert inspect_disposable_fixture(other, tmp_path)["reason"] == "unexpected_fixture_path"
    assert other.read_bytes() == b"untouched"
