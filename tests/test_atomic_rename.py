"""Test Linux no-overwrite renames using temporary folders."""

import errno
import sys

import pytest

from app.atomic_rename import rename_directory_noreplace

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux-only primitive")


def test_rename_to_absent_destination(tmp_path):
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.mkdir()
    (source / "payload").write_text("original")
    rename_directory_noreplace(source, destination)
    assert not source.exists()
    assert (destination / "payload").read_text() == "original"


def test_existing_empty_destination_is_not_replaced(tmp_path):
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    (source / "payload").write_text("original")
    with pytest.raises(OSError) as caught:
        rename_directory_noreplace(source, destination)
    assert caught.value.errno in (errno.EEXIST, errno.ENOTEMPTY)
    assert (source / "payload").read_text() == "original"
    assert destination.is_dir()


def test_existing_file_destination_is_not_replaced(tmp_path):
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.mkdir()
    destination.write_text("other")
    with pytest.raises(OSError):
        rename_directory_noreplace(source, destination)
    assert source.is_dir()
    assert destination.read_text() == "other"


