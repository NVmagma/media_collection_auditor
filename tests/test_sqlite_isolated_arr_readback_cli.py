"""Operator readback reports never leak credentials or grant recovery authority."""
import json
import pytest
import scripts.sqlite_isolated_arr_readback as module


def test_env_credentials_are_passed_only_to_get_adapter(monkeypatch, capsys):
    monkeypatch.setenv("RADARR_URL", "https://private.invalid")
    monkeypatch.setenv("RADARR_API_KEY", "private-key")
    calls = []
    def inspect(**kwargs):
        calls.append(kwargs)
        return {"status": "blocked", "observation": "matching_record_unverified",
                "clearance_authorized": False, "retry_authorized": False,
                "production_activation": "disabled"}
    monkeypatch.setattr(module, "inspect_isolated_arr_http", inspect)
    assert module.main(["--root", "/fixture/lab"]) == 0
    assert calls[0]["radarr_key"] == "private-key"
    assert calls[0]["root"] == "/fixture/lab"
    output = capsys.readouterr().out
    assert "private" not in output and "/fixture" not in output
    assert not json.loads(output)["clearance_authorized"]


@pytest.mark.parametrize("error", [RuntimeError, OSError, ValueError])
def test_failed_inspection_is_redacted_and_nonzero(monkeypatch, capsys, error):
    def fail(**kwargs):
        raise error("secret token private URL")
    monkeypatch.setattr(module, "inspect_isolated_arr_http", fail)
    assert module.main(["--root", "/fixture/lab"]) == 2
    output = capsys.readouterr().out
    assert "secret" not in output and "private" not in output
    assert json.loads(output)["production_activation"] == "disabled"
