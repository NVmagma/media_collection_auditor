"""Disposable filesystem tests; never move media or write SQLite state."""

from app.sqlite_lifecycle_observation import observe_lifecycle_location

STAGES = ("transient", "holding", "removal", "keep")


def _paths(tmp_path):
    paths = {}
    for stage in STAGES:
        root = tmp_path / stage
        root.mkdir()
        paths[stage] = str(root / "Example")
    return paths


def test_unique_stage_observed_without_authorization(tmp_path):
    paths = _paths(tmp_path)
    from pathlib import Path
    Path(paths["holding"]).mkdir()
    result = observe_lifecycle_location(paths)
    assert result["status"] == "observed"
    assert result["stage"] == "holding"
    assert result["observation"] == "unique"
    assert result["authorization"] == "not_authorized"
    assert result["checkpoint_allowed"] is False


def test_missing_title_blocks(tmp_path):
    result = observe_lifecycle_location(_paths(tmp_path))
    assert result["status"] == "blocked"
    assert result["reason"] == "media_missing"


def test_duplicate_title_blocks(tmp_path):
    from pathlib import Path
    paths = _paths(tmp_path)
    Path(paths["holding"]).mkdir()
    Path(paths["keep"]).mkdir()
    result = observe_lifecycle_location(paths)
    assert result["reason"] == "media_ambiguous"


def test_symlink_title_blocks(tmp_path):
    from pathlib import Path
    paths = _paths(tmp_path)
    Path(paths["holding"]).mkdir()
    Path(paths["keep"]).symlink_to(paths["holding"], target_is_directory=True)
    result = observe_lifecycle_location(paths)
    assert result["reason"] == "unsafe_or_unavailable_path"


def test_invalid_or_shared_paths_block(tmp_path):
    paths = _paths(tmp_path)
    paths["keep"] = paths["holding"]
    assert observe_lifecycle_location(paths)["reason"] == "duplicate_stage_paths"
    assert observe_lifecycle_location({"holding": paths["holding"]})["reason"] == "invalid_stage_paths"


def test_regular_file_blocks(tmp_path):
    from pathlib import Path
    paths = _paths(tmp_path)
    Path(paths["holding"]).write_text("not a directory")
    assert observe_lifecycle_location(paths)["reason"] == "unsafe_or_unavailable_path"
