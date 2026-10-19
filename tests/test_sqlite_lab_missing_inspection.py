"""Both-missing SQLite recovery inspection must fail closed."""
import pytest
from scripts.sqlite_lab_missing_inspection import run, PREFIX


def test_missing_both_stays_blocked(tmp_path, capsys):
    run("create", tmp_path)
    run("verify", tmp_path)
    assert "status=blocked" in capsys.readouterr().out
    with pytest.raises(RuntimeError, match="Existing fixture"):
        run("create", tmp_path)


def test_verify_without_database_refused(tmp_path):
    with pytest.raises(Exception):
        run("verify", tmp_path)


def test_symlinked_path_refused(tmp_path):
    (tmp_path / (PREFIX + "_source")).symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(RuntimeError, match="Symlinked"):
        run("create", tmp_path)


def test_existing_directory_refused(tmp_path):
    (tmp_path / (PREFIX + "_destination")).mkdir()
    with pytest.raises(RuntimeError, match="Existing fixture"):
        run("create", tmp_path)
