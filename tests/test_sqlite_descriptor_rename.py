"""Descriptor-relative Linux rename against disposable directory fixtures."""
import errno
import os
import sys

import pytest

from app.sqlite_noreplace_rename import rename_directory_noreplace_at

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux-only primitive")


@pytest.fixture
def parents(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    (source / "Movie").mkdir()
    (source / "Movie" / "payload").write_text("original")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    source_fd, destination_fd = os.open(source, flags), os.open(destination, flags)
    try:
        yield source, destination, source_fd, destination_fd
    finally:
        os.close(source_fd)
        os.close(destination_fd)


def test_held_parent_rename_preserves_payload(parents):
    source, destination, src_fd, dst_fd = parents
    rename_directory_noreplace_at(src_fd, "Movie", dst_fd, "Movie")
    assert not (source / "Movie").exists()
    assert (destination / "Movie" / "payload").read_text() == "original"


def test_replaced_destination_parent_cannot_redirect_syscall(parents):
    source, destination, src_fd, dst_fd = parents
    held = destination.with_name("original_destination")
    destination.rename(held)
    destination.mkdir()
    (destination / "Movie").mkdir()
    (destination / "Movie" / "payload").write_text("unrelated")
    rename_directory_noreplace_at(src_fd, "Movie", dst_fd, "Movie")
    assert (held / "Movie" / "payload").read_text() == "original"
    assert (destination / "Movie" / "payload").read_text() == "unrelated"


def test_replaced_source_parent_cannot_redirect_syscall(parents):
    source, destination, src_fd, dst_fd = parents
    source.rename(source.with_name("original_source"))
    source.mkdir()
    (source / "Movie").mkdir()
    (source / "Movie" / "payload").write_text("unrelated")
    rename_directory_noreplace_at(src_fd, "Movie", dst_fd, "Movie")
    assert (source / "Movie" / "payload").read_text() == "unrelated"
    assert (destination / "Movie" / "payload").read_text() == "original"


def test_competing_destination_is_not_overwritten(parents):
    source, destination, src_fd, dst_fd = parents
    (destination / "Movie").mkdir()
    with pytest.raises(OSError) as error:
        rename_directory_noreplace_at(src_fd, "Movie", dst_fd, "Movie")
    assert error.value.errno in (errno.EEXIST, errno.ENOTEMPTY)
    assert (source / "Movie" / "payload").read_text() == "original"


@pytest.mark.parametrize("name", ["", ".", "..", "../Movie", "/Movie", "a/b", "a\\b", "a\x00b"])
def test_non_component_names_rejected(parents, name):
    source, destination, src_fd, dst_fd = parents
    with pytest.raises(ValueError):
        rename_directory_noreplace_at(src_fd, name, dst_fd, "Movie")
    assert (source / "Movie").is_dir()
    assert not (destination / "Movie").exists()
