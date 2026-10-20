"""Portable copy staging without renameat2, deletion or tracking changes."""
import pytest

import app.sqlite_disposable_copy_stage as module
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS


def lab(tmp_path):
    root = tmp_path / "lab"
    root.mkdir()
    (root / ".sqlite_disposable_rehearsal").write_text("DISPOSABLE ONLY\n")
    (root / "transient" / "Movie A" / "Extras").mkdir(parents=True)
    (root / "transient" / "Movie A" / "video.bin").write_bytes(b"synthetic media" * 100)
    (root / "transient" / "Movie A" / "Extras" / "notes.txt").write_text("fixture")
    (root / "transient" / "Movie A" / "Empty").mkdir()
    state = {section: {} for section in SECTIONS}
    state["first_seen"]["Movie A"] = "2024-01-01T00:00:00"
    write_offline_snapshot(state, root / "state.db")
    return root


def run(root, operation="copy-one"):
    return module.stage_disposable_verified_copy(root=root, title_folder="Movie A", operation_id=operation)


def test_verified_copy_retains_source_database_and_nested_content(tmp_path):
    root = lab(tmp_path)
    before = (root / "state.db").read_bytes()
    result = run(root)
    assert result == {"status": "staged_copy_verified", "source_retained": True,
                      "files_verified": 2, "tracking_committed": False,
                      "promotion_authorized": False, "production_activation": "disabled"}
    source = root / "transient" / "Movie A"
    destination = root / ".sqlite_copy_staging" / "copy-one"
    assert (destination / "video.bin").read_bytes() == (source / "video.bin").read_bytes()
    assert (destination / "Extras" / "notes.txt").read_text() == "fixture"
    assert (destination / "Empty").is_dir()
    assert (root / "state.db").read_bytes() == before


def test_existing_staging_slot_is_never_overwritten(tmp_path):
    root = lab(tmp_path)
    run(root)
    staged = root / ".sqlite_copy_staging" / "copy-one" / "video.bin"
    staged.write_bytes(b"preserve existing")
    with pytest.raises(FileExistsError):
        run(root)
    assert staged.read_bytes() == b"preserve existing"
    assert (root / "transient" / "Movie A" / "video.bin").exists()


def test_source_mutation_during_copy_blocks_verification(tmp_path, monkeypatch):
    root = lab(tmp_path)
    before = (root / "state.db").read_bytes()
    original = module._copy_tree
    mutated = False
    def changing_copy(source, destination):
        nonlocal mutated
        original(source, destination)
        if not mutated:
            mutated = True
            (root / "transient" / "Movie A" / "video.bin").write_bytes(b"changed")
    monkeypatch.setattr(module, "_copy_tree", changing_copy)
    with pytest.raises(RuntimeError, match="verification mismatch|changed"):
        run(root)
    assert (root / "state.db").read_bytes() == before
    assert (root / "transient" / "Movie A" / "video.bin").exists()


def test_symlink_source_is_rejected_without_copying_target(tmp_path):
    root = lab(tmp_path)
    unrelated = tmp_path / "unrelated"
    unrelated.write_text("private")
    (root / "transient" / "Movie A" / "alias").symlink_to(unrelated)
    with pytest.raises(RuntimeError, match="symlinks"):
        run(root)
    assert unrelated.read_text() == "private"
    assert not (root / ".sqlite_copy_staging").exists()


def test_copy_error_preserves_partial_stage_and_never_updates_tracking(tmp_path, monkeypatch):
    root = lab(tmp_path)
    before = (root / "state.db").read_bytes()
    def interrupted(source, destination):
        raise OSError("simulated disk full")
    monkeypatch.setattr(module, "_copy_tree", interrupted)
    with pytest.raises(OSError, match="disk full"):
        run(root)
    assert (root / ".sqlite_copy_staging" / "copy-one").is_dir()
    assert (root / "transient" / "Movie A" / "video.bin").exists()
    assert (root / "state.db").read_bytes() == before


def test_staging_symlink_is_rejected(tmp_path):
    root = lab(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    (root / ".sqlite_copy_staging").symlink_to(other, target_is_directory=True)
    with pytest.raises(RuntimeError, match="Safe private staging"):
        run(root)
    assert list(other.iterdir()) == []


def test_pending_intent_blocks_copy_staging(tmp_path):
    from app.state_store import GuardedSQLiteStateStore
    root = lab(tmp_path)
    store = GuardedSQLiteStateStore(root / "state.db")
    state, revision = store.load_with_revision()
    state["sqlite_pending_operations"] = {"id": "unresolved"}
    store.save_if_revision(state, revision)
    before = (root / "state.db").read_bytes()
    with pytest.raises(RuntimeError, match="Unresolved"):
        run(root)
    assert (root / "state.db").read_bytes() == before
    assert not (root / ".sqlite_copy_staging").exists()


def test_mismatch_diagnostics_distinguish_metadata_without_exposing_names():
    before = {"private-title/file": ("file", 10, "private-digest")}
    identities = {"private-title/file": (1, 2, 10, 100, 200)}
    changed = {"private-title/file": (1, 2, 10, 100, 201)}
    error = module.CopyVerificationError(before, dict(before), identities, changed, dict(before))
    assert error.diagnostics["source_content_unchanged"] is True
    assert error.diagnostics["destination_content_matches"] is True
    assert error.diagnostics["source_metadata_unchanged"] is False
    assert error.diagnostics["metadata_change_counts"]["ctime_ns"] == 1
    assert "private-title" not in str(error)
    assert "private-digest" not in str(error)


def test_mismatch_diagnostics_identify_incomplete_copy():
    before = {"file": ("file", 10, "digest")}
    identities = {"file": (1, 2, 10, 100, 200)}
    error = module.CopyVerificationError(before, before, identities, identities, {})
    assert error.diagnostics["source_content_unchanged"] is True
    assert error.diagnostics["source_metadata_unchanged"] is True
    assert error.diagnostics["destination_content_matches"] is False
    assert error.diagnostics["destination_entries"] == 0
