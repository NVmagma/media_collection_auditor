"""Disposable destination-only inspection regression tests."""
import pytest
from scripts.sqlite_lab_destination_inspection import run, PREFIX


def test_destination_only_inspection_stays_blocked(tmp_path, capsys):
    run("create", tmp_path)
    run("verify", tmp_path)
    assert "status=blocked" in capsys.readouterr().out
    with pytest.raises(RuntimeError, match="Existing fixture"):
        run("create", tmp_path)


def test_missing_database_fails_closed(tmp_path):
    with pytest.raises(RuntimeError):
        run("verify", tmp_path)


def test_symlink_refused(tmp_path):
    (tmp_path / (PREFIX + ".db")).symlink_to(tmp_path / "other")
    with pytest.raises(RuntimeError, match="Symlinked"):
        run("create", tmp_path)
