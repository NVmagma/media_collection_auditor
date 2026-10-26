"""Hash evidence stays bound across fresh collection; never restart authority."""
from datetime import timedelta
import errno
import os
import sys

import pytest

from app.sqlite_copy_live_verification import _metadata_snapshot, refresh_hashed_copy
from app.sqlite_disposable_copy_stage import FLAGS, _manifest
from app.sqlite_collected_isolated_runner import run_collected_isolated_copy_completion
from app.state_store import GuardedSQLiteStateStore
from tests.test_sqlite_collected_isolated_runner import lab, item, transport, NOW, FOLDER, LIMITS


@pytest.mark.parametrize("change", ["none", "bytes", "replace", "add", "remove", "symlink", "directory"])
def test_fresh_collection_does_not_adopt_changed_hashed_tree(tmp_path, change):
    tree = tmp_path / "tree"
    (tree / "nested").mkdir(parents=True)
    (tree / "nested" / "payload").write_bytes(b"fixture")
    (tree / "empty").mkdir()
    fd = os.open(tree, FLAGS)
    try:
        _, metadata = _manifest(fd)
        assert _metadata_snapshot(fd) == metadata
        def refresh():
            path = tree / "nested" / "payload"
            if change == "bytes":
                path.write_bytes(b"changed bytes")
            elif change == "replace":
                path.rename(tree / "preserved")
                path.write_bytes(b"fixture")
            elif change == "add":
                (tree / "new").write_bytes(b"new")
            elif change == "remove":
                path.unlink()
            elif change == "symlink":
                path.rename(tree / "preserved")
                path.symlink_to(tree / "preserved")
            elif change == "directory":
                (tree / "empty").rename(tree / "old-empty")
                (tree / "empty").mkdir()
        checks = []
        if change == "none":
            refresh_hashed_copy(trees=((fd, metadata),), refresh=refresh,
                                check_window=lambda: checks.append(True))
            assert checks == [True]
            assert _metadata_snapshot(fd) == metadata  # independent directory cursors
        else:
            with pytest.raises(RuntimeError, match="changed|symlinks"):
                refresh_hashed_copy(trees=((fd, metadata),), refresh=refresh,
                                    check_window=lambda: checks.append(True))
            assert checks == []
    finally:
        os.close(fd)


def test_slow_metadata_verification_cannot_skip_deadline(tmp_path):
    fd = os.open(tmp_path, FLAGS)
    try:
        metadata = _metadata_snapshot(fd)
        def expired():
            raise RuntimeError("window expired")
        with pytest.raises(RuntimeError, match="window expired"):
            refresh_hashed_copy(trees=((fd, metadata),), refresh=lambda: None, check_window=expired)
    finally:
        os.close(fd)


@pytest.mark.parametrize("phase,target", [(2, "source"), (4, "source"), (4, "staging")])
def test_mutation_during_fresh_scan_blocks_before_media_action(tmp_path, phase, target):
    root, database = lab(tmp_path)
    before = database.read_bytes()
    base_fetch, calls = transport([[item()]])
    changed = False
    def fetch(*args, **kwargs):
        nonlocal changed
        result = base_fetch(*args, **kwargs)
        if not changed and calls.count("/Users") == phase:
            changed = True
            path = root / ("transient" if target == "source" else ".sqlite_copy_staging") / (FOLDER if target == "source" else "complete-copy") / "payload"
            path.write_bytes(b"concurrent writer")
        return result
    with pytest.raises(RuntimeError, match="metadata changed"):
        run_collected_isolated_copy_completion(root=root, database=database,
            operation_id="complete-copy", media_key=FOLDER, title_folder=FOLDER,
            jellyfin_type="Movie", thresholds=LIMITS, fetch=fetch, clock=lambda: NOW)
    state = GuardedSQLiteStateStore(database).load_with_revision()[0]
    assert FOLDER in state["first_seen"] and not state["queued"] and not state["arr_sync_pending"]
    assert not (root / "holding" / FOLDER).exists()
    assert (root / "transient" / FOLDER / "payload").exists()
    if phase == 2:
        assert database.read_bytes() == before
        assert "sqlite_pending_operations" not in state
    else:
        assert "publication" not in state["sqlite_pending_operations"]["details"]


def test_long_hashes_use_fresh_windows_without_skipping_content_verification(tmp_path, monkeypatch):
    import app.sqlite_disposable_copy_stage as stage
    import app.sqlite_disposable_copy_publication as publication
    import app.sqlite_disposable_copy_completion as completion
    import app.sqlite_disposable_copy_inspection as inspection
    root, database = lab(tmp_path)
    elapsed, hashes = 0, 0
    original = stage._manifest
    def slow_hash(*args, **kwargs):
        nonlocal elapsed, hashes
        result = original(*args, **kwargs)
        elapsed += 120
        hashes += 1
        return result
    for module in (stage, publication, completion, inspection):
        monkeypatch.setattr(module, "_manifest", slow_hash)
    fetch, calls = transport([[item()]])
    try:
        result = run_collected_isolated_copy_completion(root=root, database=database,
            operation_id="complete-copy", media_key=FOLDER, title_folder=FOLDER,
            jellyfin_type="Movie", thresholds=LIMITS, fetch=fetch,
            clock=lambda: NOW + timedelta(seconds=elapsed), timer=lambda: elapsed)
    except RuntimeError as exc:
        assert str(exc) in ("Atomic no-replace rename requires Linux", "Atomic no-replace rename unsupported")
        if sys.platform == "linux":
            assert isinstance(exc.__cause__, OSError)
            assert exc.__cause__.errno in (errno.EINVAL, errno.ENOSYS, errno.EOPNOTSUPP, errno.ENOTSUP)
        state = GuardedSQLiteStateStore(database).load_with_revision()[0]
        assert state["sqlite_pending_operations"]["details"]["publication"]["phase"] == "prepared"
        assert hashes >= 10 and calls.count("/Users") == 5
        original_path = root / "transient" / FOLDER
    else:
        assert result["lifecycle_committed"] and result["original_bytes_retained"]
        assert hashes >= 16 and calls.count("/Users") == 9
        original_path = root / ".sqlite_retained_sources" / "complete-copy"
    assert (original_path / "payload").read_text() == "fixture"


@pytest.mark.parametrize("scans", [3, 5])
def test_slow_tree_walk_expires_actual_collection_window(tmp_path, monkeypatch, scans):
    import app.sqlite_copy_live_verification as verification
    root, database = lab(tmp_path)
    elapsed = 0
    fetch, calls = transport([[item()]])
    original = verification._metadata_snapshot
    def slow_walk(*args, **kwargs):
        nonlocal elapsed
        result = original(*args, **kwargs)
        if calls.count("/Users") == scans:
            elapsed += 61
        return result
    monkeypatch.setattr(verification, "_metadata_snapshot", slow_walk)
    with pytest.raises(RuntimeError, match="window expired"):
        run_collected_isolated_copy_completion(root=root, database=database,
            operation_id="complete-copy", media_key=FOLDER, title_folder=FOLDER,
            jellyfin_type="Movie", thresholds=LIMITS, fetch=fetch,
            clock=lambda: NOW, timer=lambda: elapsed)
    state = GuardedSQLiteStateStore(database).load_with_revision()[0]
    assert FOLDER in state["first_seen"] and not state["queued"]
    assert (root / "transient" / FOLDER / "payload").read_text() == "fixture"
    assert not (root / "holding" / FOLDER).exists()
    if scans == 3:
        assert "sqlite_pending_operations" not in state
    else:
        assert "publication" not in state["sqlite_pending_operations"]["details"]
