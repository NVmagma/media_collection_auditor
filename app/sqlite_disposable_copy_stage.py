"""Portable copy/verification building block for marked disposable labs.

No renameat2, filesystem-name policy, source removal, tracking checkpoint,
notification, promotion, automatic retry or production caller.
"""
import hashlib
import json
import os
from pathlib import Path
import stat

from app.sqlite_isolated_lifecycle_runner import isolated_runner_lock
from app.sqlite_title_identity import validate_title_folder
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.state_store import GuardedSQLiteStateStore

FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


class CopyVerificationError(RuntimeError):
    """Aggregate mismatch diagnostics only; no source names or content digests."""
    def __init__(self, before, after, identities, after_identities, copied):
        fields = ("device", "inode", "size", "mtime_ns", "ctime_ns")
        common = set(identities) & set(after_identities)
        summary = {
            "source_content_unchanged": before == after,
            "source_metadata_unchanged": identities == after_identities,
            "destination_content_matches": copied == before,
            "source_entries_before": len(before),
            "source_entries_after": len(after),
            "destination_entries": len(copied),
            "source_identity_keys_unchanged": set(identities) == set(after_identities),
            "metadata_changed_directories": sum(
                identities[key] != after_identities[key] for key in common
                if not key or key.endswith("/")),
            "metadata_changed_files": sum(
                identities[key] != after_identities[key] for key in common
                if key and not key.endswith("/")),
            "metadata_change_counts": {
                field: sum(identities[key][index] != after_identities[key][index] for key in common)
                for index, field in enumerate(fields)
            },
        }
        self.diagnostics = summary
        super().__init__("Staged copy verification mismatch; source retained; " +
                         json.dumps(summary, sort_keys=True))


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _directory_names(directory_fd):
    # openat(".") creates an independent open file description/cursor. dup()
    # would share the held descriptor's directory offset across scan passes.
    scan_fd = os.open(".", FLAGS, dir_fd=directory_fd)
    try:
        return sorted(os.listdir(scan_fd))
    finally:
        os.close(scan_fd)


def _manifest(directory_fd, prefix=""):
    content, identities = {}, {}
    identities[prefix] = _identity(os.fstat(directory_fd))
    for name in _directory_names(directory_fd):
        relative = prefix + name
        info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            fd = os.open(name, FLAGS, dir_fd=directory_fd)
            try:
                if _identity(os.fstat(fd)) != _identity(info):
                    raise RuntimeError("Source directory changed during verification")
                content[relative] = ("directory",)
                children, observed = _manifest(fd, relative + "/")
                content.update(children)
                identities.update(observed)
            finally:
                os.close(fd)
        elif stat.S_ISREG(info.st_mode):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
            try:
                if _identity(os.fstat(fd)) != _identity(info):
                    raise RuntimeError("Source file changed during verification")
                digest = hashlib.sha256()
                size = 0
                while block := os.read(fd, 1024 * 1024):
                    size += len(block)
                    digest.update(block)
                if _identity(os.fstat(fd)) != _identity(info):
                    raise RuntimeError("File changed during verification")
                content[relative] = ("file", size, digest.hexdigest())
                identities[relative] = _identity(info)
            finally:
                os.close(fd)
        else:
            raise RuntimeError("Copy staging refuses symlinks and special files")
    return content, identities


def _copy_tree(source_fd, destination_fd):
    for name in _directory_names(source_fd):
        info = os.stat(name, dir_fd=source_fd, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            source_child = os.open(name, FLAGS, dir_fd=source_fd)
            try:
                if _identity(os.fstat(source_child)) != _identity(info):
                    raise RuntimeError("Source directory changed during copy")
                os.mkdir(name, mode=0o700, dir_fd=destination_fd)
                destination_child = os.open(name, FLAGS, dir_fd=destination_fd)
                try:
                    _copy_tree(source_child, destination_child)
                    os.fsync(destination_child)
                finally:
                    os.close(destination_child)
            finally:
                os.close(source_child)
        elif stat.S_ISREG(info.st_mode):
            source_file = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=source_fd)
            try:
                if _identity(os.fstat(source_file)) != _identity(info):
                    raise RuntimeError("Source file changed during copy")
                destination_file = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                           0o600, dir_fd=destination_fd)
                try:
                    while block := os.read(source_file, 1024 * 1024):
                        remaining = memoryview(block)
                        while remaining:
                            written = os.write(destination_file, remaining)
                            if written <= 0:
                                raise RuntimeError("Incomplete staged copy")
                            remaining = remaining[written:]
                    os.fsync(destination_file)
                finally:
                    os.close(destination_file)
                if _identity(os.fstat(source_file)) != _identity(info):
                    raise RuntimeError("Source file changed during copy")
            finally:
                os.close(source_file)
        else:
            raise RuntimeError("Copy staging refuses symlinks and special files")
    os.fsync(destination_fd)


def stage_disposable_verified_copy(*, root, title_folder, operation_id):
    """Create an exclusive hidden staged copy; retain source and tracking state.

    Requires trusted local transport primitives (exclusive create, fsync, reads).
    Errors preserve any partial staging for inspection. Never overwrite/resume.
    """
    root = Path(root)
    folder = validate_title_folder(title_folder)
    operation = validate_title_folder(operation_id)
    with isolated_runner_lock(root) as verify_binding:
        state, _ = GuardedSQLiteStateStore(root / "state.db").load_with_revision()
        if INTENTS_KEY in state:
            raise RuntimeError("Unresolved operation; copy staging stopped")
        source_parent = root / "transient"
        if source_parent.is_symlink() or not source_parent.is_dir():
            raise RuntimeError("Safe disposable source stage required")
        source_path = source_parent / folder
        if source_path.resolve() != source_path:
            raise RuntimeError("Source aliases refused")
        source_fd = os.open(source_path, FLAGS)
        stage_parent_fd = stage_fd = None
        try:
            original_source = os.fstat(source_fd)
            before, identities = _manifest(source_fd)
            stage_parent = root / ".sqlite_copy_staging"
            if not stage_parent.exists():
                stage_parent.mkdir(mode=0o700)
            if stage_parent.is_symlink() or not stage_parent.is_dir():
                raise RuntimeError("Safe private staging directory required")
            stage_parent_fd = os.open(stage_parent, FLAGS)
            original_stage_parent = os.fstat(stage_parent_fd)
            os.mkdir(operation, mode=0o700, dir_fd=stage_parent_fd)
            stage_fd = os.open(operation, FLAGS, dir_fd=stage_parent_fd)
            original_stage = os.fstat(stage_fd)
            _copy_tree(source_fd, stage_fd)
            after, after_identities = _manifest(source_fd)
            copied, _ = _manifest(stage_fd)
            if before != after or identities != after_identities or copied != before:
                raise CopyVerificationError(before, after, identities, after_identities, copied)
            source_current = os.stat(source_path, follow_symlinks=False)
            stage_current = os.stat(operation, dir_fd=stage_parent_fd, follow_symlinks=False)
            if ((source_current.st_dev, source_current.st_ino) != (original_source.st_dev, original_source.st_ino)
                    or (stage_current.st_dev, stage_current.st_ino) != (original_stage.st_dev, original_stage.st_ino)):
                raise RuntimeError("Copy path binding changed; source retained")
            parent_current = os.stat(stage_parent, follow_symlinks=False)
            if (parent_current.st_dev, parent_current.st_ino) != (original_stage_parent.st_dev, original_stage_parent.st_ino):
                raise RuntimeError("Staging parent changed; source retained")
            os.fsync(stage_parent_fd)
            root_fd = os.open(root, FLAGS)
            try:
                os.fsync(root_fd)
            finally:
                os.close(root_fd)
            verify_binding()
            return {"status": "staged_copy_verified", "source_retained": True,
                    "files_verified": sum(entry[0] == "file" for entry in before.values()),
                    "tracking_committed": False, "promotion_authorized": False,
                    "production_activation": "disabled"}
        finally:
            if stage_fd is not None:
                os.close(stage_fd)
            if stage_parent_fd is not None:
                os.close(stage_parent_fd)
            os.close(source_fd)
