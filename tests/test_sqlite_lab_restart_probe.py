"""Lab restart probe never overwrites existing markers or modifies on verify."""
import json
import pytest
from scripts import sqlite_lab_restart_probe as probe


def test_create_verify_and_exclusive_marker(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(probe, "LAB", tmp_path)
    monkeypatch.setattr(probe, "MARKER", tmp_path / "sqlite_restart_probe.json")
    probe.probe("create")
    original = probe.MARKER.read_bytes()
    probe.probe("verify")
    assert "sha256=" in capsys.readouterr().out
    assert probe.MARKER.read_bytes() == original
    with pytest.raises(FileExistsError):
        probe.probe("create")


def test_tampering_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "LAB", tmp_path)
    monkeypatch.setattr(probe, "MARKER", tmp_path / "sqlite_restart_probe.json")
    probe.MARKER.write_text(json.dumps({"schema": 1, "state": "cleared"}))
    with pytest.raises(RuntimeError, match="differ"):
        probe.probe("verify")


def test_missing_mount_does_not_create_files(tmp_path, monkeypatch):
    missing = tmp_path / "missing"
    monkeypatch.setattr(probe, "LAB", missing)
    monkeypatch.setattr(probe, "MARKER", missing / "sqlite_restart_probe.json")
    with pytest.raises(RuntimeError, match="Missing"):
        probe.probe("create")
    assert not missing.exists()
