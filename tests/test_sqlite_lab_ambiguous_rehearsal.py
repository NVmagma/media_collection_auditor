"""Disposable ambiguous recovery rehearsal tests."""
import pytest
from scripts.sqlite_lab_ambiguous_rehearsal import run


@pytest.mark.parametrize("scenario", ["source_only", "both_present"])
def test_reopen_inspection_never_authorizes(tmp_path, scenario, capsys):
    run("create", scenario, tmp_path)
    run("verify", scenario, tmp_path)
    assert "status=blocked" in capsys.readouterr().out
    with pytest.raises(RuntimeError, match="Existing fixture"):
        run("create", scenario, tmp_path)


def test_missing_fixture_refused(tmp_path):
    with pytest.raises(RuntimeError):
        run("verify", "source_only", tmp_path)


def test_invalid_scenario_refused(tmp_path):
    with pytest.raises(RuntimeError, match="Expected"):
        run("create", "unknown", tmp_path)
