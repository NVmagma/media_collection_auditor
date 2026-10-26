"""Linux no-replace primitive tests against disposable directories."""

import errno
import sys

import pytest

from app.sqlite_noreplace_rename import rename_directory_noreplace

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux-only primitive")


def test_rename_to_absent_destination(tmp_path):
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.mkdir()
    (source / "payload").write_text("original")
    rename_directory_noreplace(source, destination)
    assert not source.exists()
    assert (destination / "payload").read_text() == "original"


def test_existing_empty_destination_is_not_replaced(tmp_path):
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    (source / "payload").write_text("original")
    with pytest.raises(OSError) as caught:
        rename_directory_noreplace(source, destination)
    assert caught.value.errno in (errno.EEXIST, errno.ENOTEMPTY)
    assert (source / "payload").read_text() == "original"
    assert destination.is_dir()


def test_existing_file_destination_is_not_replaced(tmp_path):
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.mkdir()
    destination.write_text("other")
    with pytest.raises(OSError):
        rename_directory_noreplace(source, destination)
    assert source.is_dir()
    assert destination.read_text() == "other"


def test_destination_created_after_preflight_is_preserved(tmp_path, monkeypatch):
    import app.sqlite_disposable_lifecycle_flow as flow
    from app.sqlite_audit_session import RevisionedAuditSession
    from app.sqlite_operation_coordinator import INTENTS_KEY
    from app.sqlite_snapshot_writer import write_offline_snapshot
    from app.sqlite_state import SECTIONS
    from app.state_store import GuardedSQLiteStateStore
    from datetime import datetime

    root = tmp_path / "lab"
    root.mkdir()
    (root / ".sqlite_disposable_rehearsal").write_text("DISPOSABLE ONLY\n")
    for stage in ("transient", "holding", "removal", "keep"):
        (root / stage).mkdir()
    source = root / "transient" / "Movie"
    source.mkdir()
    (source / "payload").write_text("original")
    database = root / "state.db"
    state = {section: {} for section in SECTIONS}
    state["first_seen"]["DISPOSABLE/Movie"] = "2024-01-01T00:00:00"
    write_offline_snapshot(state, database)

    actual = flow.rename_directory_noreplace

    def racing_rename(src, dst):
        dst.mkdir()
        (dst / "payload").write_text("competitor")
        return actual(src, dst)

    monkeypatch.setattr(flow, "rename_directory_noreplace", racing_rename)
    with pytest.raises(OSError):
        flow.execute_disposable_lifecycle_move(
            root=root, database=database, operation_id="op-1",
            media_key="DISPOSABLE/Movie", observed_at=datetime(2024, 2, 1))
    assert (source / "payload").read_text() == "original"
    assert (root / "holding" / "Movie" / "payload").read_text() == "competitor"
    persisted = RevisionedAuditSession(GuardedSQLiteStateStore(database)).state
    assert INTENTS_KEY in persisted
    assert "DISPOSABLE/Movie" in persisted["first_seen"]
