"""Offline rehearsal regression tests; no services or real media."""
import pytest
from scripts.sqlite_lab_intent_rehearsal import run, DATABASE_NAME, SOURCE_NAME, DEST_NAME


def test_intent_survives_reopening_and_stays_blocked(tmp_path, capsys):
    run("create", tmp_path)
    run("verify", tmp_path)
    assert "status=blocked" in capsys.readouterr().out
    assert not (tmp_path / DEST_NAME).exists()
    with pytest.raises(RuntimeError, match="already exist"):
        run("create", tmp_path)


def test_missing_or_modified_source_fails_closed(tmp_path):
    run("create", tmp_path)
    (tmp_path / SOURCE_NAME).rmdir()
    with pytest.raises(RuntimeError, match="filesystem changed"):
        run("verify", tmp_path)


def test_missing_database_fails_closed(tmp_path):
    with pytest.raises(RuntimeError):
        run("verify", tmp_path)
    assert not (tmp_path / DATABASE_NAME).exists()
