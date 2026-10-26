"""Regression checks for fail-closed SQLite lab path/image preflight."""
import pytest
from scripts.sqlite_lab_preflight import check_lab_environment


def settings(path):
    return {"SQLITE_LAB_DIR": str(path), "SQLITE_LAB_UID": "1000",
            "SQLITE_LAB_GID": "1000",
            "SQLITE_LAB_IMAGE": "python:3.12-slim@sha256:" + "a" * 64}


def test_dedicated_lab_accepted(tmp_path):
    lab = tmp_path / "sqlite_lab"
    lab.mkdir()
    assert check_lab_environment(settings(lab)) == lab


@pytest.mark.parametrize("key,value", [
    ("SQLITE_LAB_UID", "0"), ("SQLITE_LAB_GID", "root"),
    ("SQLITE_LAB_IMAGE", "python:3.12-slim"),
    ("SQLITE_LAB_IMAGE", "python:3.12-slim@sha256:bad"),
])
def test_unsafe_settings_rejected(tmp_path, key, value):
    lab = tmp_path / "sqlite_lab"
    lab.mkdir()
    env = settings(lab)
    env[key] = value
    with pytest.raises(RuntimeError):
        check_lab_environment(env)


@pytest.mark.parametrize("name", ["media", "movies", "logs", "media_collection_auditor"])
def test_production_named_parent_rejected(tmp_path, name):
    lab = tmp_path / name / "sqlite_lab"
    lab.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="production"):
        check_lab_environment(settings(lab))


def test_symlinked_lab_rejected(tmp_path):
    lab = tmp_path / "sqlite_lab"
    lab.mkdir()
    alias = tmp_path / "sqlite_lab_alias"
    alias.symlink_to(lab, target_is_directory=True)
    with pytest.raises(RuntimeError, match="symlink"):
        check_lab_environment(settings(alias))


def test_missing_lab_is_not_created(tmp_path):
    lab = tmp_path / "sqlite_lab"
    with pytest.raises(RuntimeError):
        check_lab_environment(settings(lab))
    assert not lab.exists()
