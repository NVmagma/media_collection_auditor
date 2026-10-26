"""Operator diagnostics are redacted and never authorize recovery."""
import json
import sqlite3
import pytest
from tests.test_sqlite_disposable_copy_intent import lab, run
from scripts.sqlite_disposable_copy_inspect import main


def test_cli_inspects_retained_copy_without_state_changes(lab, capsys):
    run(lab)
    before = (lab / "state.db").read_bytes()
    assert main(["--root", str(lab)]) == 0
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["status"] == "blocked"
    assert report["source_status"] == report["staging_status"] == "content_matches_unverified"
    assert not report["recovery_authorized"]
    assert str(lab) not in output and "Movie A" not in output
    assert (lab / "state.db").read_bytes() == before


def test_cli_without_pending_intent_fails_closed(lab, capsys):
    assert main(["--root", str(lab)]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "inspection_failed"
    assert not report["recovery_authorized"]


@pytest.mark.parametrize("error", [OSError, RuntimeError, ValueError, TypeError, sqlite3.DatabaseError])
def test_cli_exception_text_is_never_printed(monkeypatch, capsys, error):
    import scripts.sqlite_disposable_copy_inspect as module
    def fail(**kwargs):
        raise error("private path /secret/title token=private")
    monkeypatch.setattr(module, "inspect_disposable_copy", fail)
    assert main(["--root", "/secret/lab"]) == 2
    output = capsys.readouterr()
    assert "private" not in output.out and "/secret" not in output.out
    assert output.err == ""
    assert json.loads(output.out)["production_activation"] == "disabled"
