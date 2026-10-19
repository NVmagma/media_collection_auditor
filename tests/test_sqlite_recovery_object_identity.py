"""Filesystem object diagnostics must never authorize a recovery."""

from app.sqlite_recovery_object_identity import inspect_move_object_observation


def test_destination_observed_still_unverified(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    destination.mkdir()
    result = inspect_move_object_observation(str(source), str(destination))
    assert result["reason"] == "destination_object_observed_not_proven"
    assert result["object_identity"] == "unverified"
    assert result["authorization"] == "not_authorized"
    assert str(tmp_path) not in str(result)


def test_both_present_is_not_destination_only(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    result = inspect_move_object_observation(str(source), str(destination))
    assert result["reason"] == "not_destination_only"


def test_symlink_is_never_followed(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    target.mkdir()
    destination = tmp_path / "destination"
    destination.symlink_to(target, target_is_directory=True)
    result = inspect_move_object_observation(str(source), str(destination))
    assert result["reason"] == "not_destination_only"


def test_traversal_path_rejected(tmp_path):
    source = str(tmp_path / "missing")
    destination = str(tmp_path / "parent" / ".." / "target")
    result = inspect_move_object_observation(source, destination)
    assert result["reason"] == "not_destination_only"


def test_identity_does_not_change_when_destination_replaced(monkeypatch):
    from app import sqlite_recovery_object_identity as identity
    observed = iter([
        {"status": "missing"},
        {"status": "present", "device": 1, "inode": 10},
        {"status": "missing"},
        {"status": "present", "device": 1, "inode": 11},
    ])
    monkeypatch.setattr(identity, "_observe_directory", lambda _: next(observed))
    result = identity.inspect_move_object_observation("/source", "/destination")
    assert result["reason"] == "filesystem_changed_during_inspection"
