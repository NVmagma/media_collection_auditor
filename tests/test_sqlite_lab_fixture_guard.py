"""Guard tests do not mount or mutate media."""
import pytest

from scripts.sqlite_lab_fixture_guard import (
    FIXTURE_NAMES, validate_disposable_lab, validate_fixture_slot,
)


def test_fixture_names_are_fixed_and_disposable():
    assert len(FIXTURE_NAMES) == len(set(FIXTURE_NAMES))
    assert all(name.startswith("sqlite_disposable_move_") for name in FIXTURE_NAMES)


def test_reject_non_lab_directory(tmp_path):
    with pytest.raises(RuntimeError, match="Only /lab"):
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
