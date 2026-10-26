"""Container-independent regression tests for applied-phase restart safety."""
import pytest
from scripts.sqlite_lab_applied_rehearsal import run, DB_NAME


def test_applied_checkpoint_remains_blocked_after_reopen(tmp_path, capsys):
    run("create", tmp_path)
    run("verify", tmp_path)
    assert "status=blocked" in capsys.readouterr().out
    with pytest.raises(RuntimeError, match="Existing"):
        run("create", tmp_path)


def test_missing_database_fails_closed(tmp_path):
    with pytest.raises(RuntimeError):
        run("verify", tmp_path)
    assert not (tmp_path / DB_NAME).exists()
