"""Filesystem-only recovery classification on disposable directories."""

import pytest

from app.sqlite_move_reconciliation import inspect_move_intent


def _paths(tmp_path):
    source_parent = tmp_path / "Waiting"
    target_parent = tmp_path / "Keep"
    source_parent.mkdir()
    target_parent.mkdir()
    return source_parent / "Movie", target_parent / "Movie"


def test_move_not_started(tmp_path):
    source, target = _paths(tmp_path)
    source.mkdir()
    assert inspect_move_intent({"source": str(source), "destination": str(target)}) == "not_started"


def test_move_destination_present(tmp_path):
    source, target = _paths(tmp_path)
    target.mkdir()
    assert inspect_move_intent({"source": str(source), "destination": str(target)}) == "destination_present"


def test_both_present_is_ambiguous(tmp_path):
    source, target = _paths(tmp_path)
    source.mkdir()
    target.mkdir()
    with pytest.raises(RuntimeError, match="Ambiguous"):
        inspect_move_intent({"source": str(source), "destination": str(target)})


def test_both_missing_blocks_recovery(tmp_path):
    source, target = _paths(tmp_path)
    with pytest.raises(RuntimeError, match="both source and destination missing"):
        inspect_move_intent({"source": str(source), "destination": str(target)})


def test_symlinked_source_is_rejected(tmp_path):
    source, target = _paths(tmp_path)
    real = tmp_path / "real"
    real.mkdir()
    source.symlink_to(real, target_is_directory=True)
    with pytest.raises(RuntimeError, match="symlink"):
        inspect_move_intent({"source": str(source), "destination": str(target)})


def test_symlinked_parent_is_rejected(tmp_path):
    source, target = _paths(tmp_path)
    source.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(source.parent, target_is_directory=True)
    with pytest.raises(RuntimeError, match="symlink"):
        inspect_move_intent({"source": str(alias / "Movie"), "destination": str(target)})


def test_invalid_and_relative_paths_are_rejected(tmp_path):
    source, target = _paths(tmp_path)
    for details in (
        {"source": "Waiting/Movie", "destination": str(target)},
        {"source": str(source), "destination": str(source)},
        {"source": str(source), "destination": ""},
        {"source": str(source.parent / ".." / "Waiting" / "Movie"), "destination": str(target)},
    ):
        with pytest.raises(RuntimeError):
            inspect_move_intent(details)


def test_file_is_not_accepted_as_media_directory(tmp_path):
    source, target = _paths(tmp_path)
    source.write_text("not a directory")
    with pytest.raises(RuntimeError, match="not a directory"):
        inspect_move_intent({"source": str(source), "destination": str(target)})
