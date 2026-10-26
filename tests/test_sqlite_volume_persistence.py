"""Named-volume rehearsal safety on disposable temporary directories."""
import pytest
from scripts import sqlite_volume_persistence as rehearsal


def test_three_phases_persist_without_media_access(tmp_path, monkeypatch):
    monkeypatch.setattr(rehearsal, "ROOT", tmp_path)
    monkeypatch.setattr(rehearsal, "DATABASE", tmp_path / "sqlite-persistence-rehearsal.db")
    assert rehearsal.run("prepare")["status"] == "prepared"
    assert rehearsal.run("advance")["status"] == "advanced"
    assert rehearsal.run("verify")["status"] == "persisted"
    with pytest.raises(RuntimeError, match="empty"):
        rehearsal.run("prepare")


def test_unexpected_volume_contents_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(rehearsal, "ROOT", tmp_path)
    monkeypatch.setattr(rehearsal, "DATABASE", tmp_path / "sqlite-persistence-rehearsal.db")
    (tmp_path / "unrelated.txt").write_text("do not touch")
    with pytest.raises(RuntimeError, match="empty"):
        rehearsal.run("prepare")
    assert (tmp_path / "unrelated.txt").read_text() == "do not touch"
