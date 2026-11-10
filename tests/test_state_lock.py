"""Check that cooperating state writers and offline migration share the lock."""

import pytest

from app.state_lock import audit_run_lock, migration_lock, state_writer_lock


def test_second_migration_lock_is_rejected(tmp_path):
    source = tmp_path / "state.json"
    source.write_text("{}")
    with migration_lock(source):
        with pytest.raises(RuntimeError, match="Another offline migration"):
            with migration_lock(source):
                pass


def test_lock_released_after_exception(tmp_path):
    source = tmp_path / "state.json"
    source.write_text("{}")
    with pytest.raises(ValueError):
        with migration_lock(source):
            raise ValueError("simulated failure")
    with migration_lock(source):
        pass






def test_missing_source_does_not_create_lock(tmp_path):
    source = tmp_path / "missing.json"
    with pytest.raises(RuntimeError, match="missing"):
        with migration_lock(source):
            pass
    assert not (tmp_path / "missing.json.migration.lock").exists()


def test_json_writer_is_blocked_by_migration(tmp_path):
    source = tmp_path / "state.json"
    source.write_text("{}")
    with migration_lock(source):
        with pytest.raises(RuntimeError, match="blocked"):
            with state_writer_lock(source):
                pass


def test_migration_is_blocked_by_json_writer(tmp_path):
    source = tmp_path / "state.json"
    source.write_text("{}")
    with state_writer_lock(source):
        with pytest.raises(RuntimeError, match="Another offline migration"):
            with migration_lock(source):
                pass


def test_json_writer_lock_allows_fresh_state_and_releases(tmp_path):
    source = tmp_path / "state.json"
    with state_writer_lock(source):
        source.write_text("{}")
    with migration_lock(source):
        pass
    assert source.read_text() == "{}"


def test_json_writer_lock_releases_after_exception(tmp_path):
    source = tmp_path / "state.json"
    with pytest.raises(ValueError):
        with state_writer_lock(source):
            raise ValueError("simulated interrupted save")
    with state_writer_lock(source):
        pass


def test_audit_lock_blocks_migration_and_allows_nested_save(tmp_path):
    source = tmp_path / "state.json"
    source.write_text("{}")
    with audit_run_lock(source):
        with state_writer_lock(source):
            source.write_text('{"queued": {}}')
        with pytest.raises(RuntimeError, match="Another offline migration"):
            with migration_lock(source):
                pass
        with pytest.raises(RuntimeError, match="Nested auditor"):
            with audit_run_lock(source):
                pass
    with migration_lock(source):
        pass


def test_audit_lock_blocks_competing_writer_and_releases_on_error(tmp_path):
    source = tmp_path / "state.json"
    source.write_text("{}")
    with pytest.raises(ValueError, match="interrupted"):
        with audit_run_lock(source):
            raise ValueError("interrupted")
    with state_writer_lock(source):
        pass


@pytest.mark.parametrize("lock", [migration_lock, state_writer_lock, audit_run_lock])
@pytest.mark.parametrize("unsafe", ["symlink", "hardlink", "fifo"])
def test_unsafe_lock_file_is_refused(tmp_path, lock, unsafe):
    import os
    source = tmp_path / "state.json"
    source.write_text("{}")
    target = tmp_path / "preserved"
    target.write_text("preserve")
    path = tmp_path / "state.json.migration.lock"
    if unsafe == "symlink":
        path.symlink_to(target)
    elif unsafe == "hardlink":
        os.link(target, path)
    else:
        os.mkfifo(path)
    with pytest.raises((OSError, RuntimeError)):
        with lock(source):
            pytest.fail("unsafe lock must not enter")
    assert source.read_text() == "{}" and target.read_text() == "preserve"


def test_replaced_lock_blocks_nested_save_during_audit(tmp_path):
    source = tmp_path / "state.json"
    source.write_text("{}")
    path = tmp_path / "state.json.migration.lock"
    with pytest.raises(RuntimeError, match="binding changed"):
        with audit_run_lock(source):
            path.rename(tmp_path / "retained-lock")
            path.write_text("")
            with state_writer_lock(source):
                pytest.fail("nested save must validate held lock")
    assert source.read_text() == "{}"


def test_lock_replacement_on_exit_is_uncertain_failure(tmp_path):
    source = tmp_path / "state.json"
    source.write_text("{}")
    path = tmp_path / "state.json.migration.lock"
    with pytest.raises(RuntimeError, match="binding changed"):
        with migration_lock(source):
            path.rename(tmp_path / "retained-lock")
            path.write_text("")
    # Both artifacts remain; no automatic lock repair or removal.
    assert path.exists() and (tmp_path / "retained-lock").exists()
