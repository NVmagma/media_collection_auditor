"""Source parent substitution cannot produce a verified copy checkpoint."""
import pytest
import app.sqlite_disposable_copy_stage as module
from tests.test_sqlite_disposable_copy_intent import lab, run, state


@pytest.mark.parametrize("replacement", ["parent_symlink", "parent_directory", "title_symlink"])
def test_source_substitution_during_copy_retains_prepared_intent(lab, monkeypatch, replacement):
    original = module._copy_tree
    def copy(source, destination):
        original(source, destination)
        parent = lab / "transient"
        if replacement == "title_symlink":
            (parent / "Movie A").rename(lab / "retained-title")
            (parent / "Movie A").symlink_to(lab / "retained-title", target_is_directory=True)
        else:
            parent.rename(lab / "retained-parent")
            if replacement == "parent_symlink":
                parent.symlink_to(lab / "retained-parent", target_is_directory=True)
            else:
                (parent / "Movie A").mkdir(parents=True)
                (parent / "Movie A" / "payload").write_text("external replacement")
    monkeypatch.setattr(module, "_copy_tree", copy)
    with pytest.raises(RuntimeError, match="source binding changed"):
        run(lab)
    pending = state(lab)["sqlite_pending_operations"]
    assert pending["details"]["copy_phase"] == "prepared"
    assert pending["phase"] == "intent_recorded"
    assert state(lab)["first_seen"]["Movie A"] == "2024-01-01T00:00:00"
    assert (lab / ".sqlite_copy_staging" / "copy-one" / "payload").read_text() == "fixture"
    retained = lab / ("retained-title" if replacement == "title_symlink" else "retained-parent/Movie A")
    assert (retained / "payload").read_text() == "fixture"


def test_source_parent_descriptor_is_closed_on_title_open_failure(lab, monkeypatch):
    real_open, real_close = module.os.open, module.os.close
    observed, closed = [], []
    def opening(path, flags, *args, **kwargs):
        if path == "Movie A" and "dir_fd" in kwargs:
            observed.append(kwargs["dir_fd"])
            raise OSError("injected title open failure")
        return real_open(path, flags, *args, **kwargs)
    def closing(fd):
        closed.append(fd)
        return real_close(fd)
    monkeypatch.setattr(module.os, "open", opening)
    monkeypatch.setattr(module.os, "close", closing)
    with pytest.raises(OSError, match="title open"):
        run(lab)
    assert observed and observed[0] in closed
    assert "sqlite_pending_operations" not in state(lab)


def test_root_replacement_cannot_redirect_private_staging_writes(lab, monkeypatch):
    original_mkdir = module.os.mkdir
    retained = lab.parent / "retained-lab"
    substituted = False
    def mkdir(path, *args, **kwargs):
        nonlocal substituted
        if path == ".sqlite_copy_staging" and not substituted:
            substituted = True
            lab.rename(retained)
            original_mkdir(lab)
        return original_mkdir(path, *args, **kwargs)
    monkeypatch.setattr(module.os, "mkdir", mkdir)
    with pytest.raises(RuntimeError):
        run(lab)
    assert substituted and list(lab.iterdir()) == []
    assert (retained / "transient" / "Movie A" / "payload").read_text() == "fixture"
    pending = state(retained)["sqlite_pending_operations"]
    assert pending["phase"] == "intent_recorded"
    assert pending["details"]["copy_phase"] == "prepared"
    assert (retained / ".sqlite_copy_staging" / "copy-one").is_dir()
