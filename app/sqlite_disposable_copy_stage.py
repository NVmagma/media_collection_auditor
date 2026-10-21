"""Portable copy/verification building block for marked disposable labs.

No renameat2, filesystem-name policy, source removal, lifecycle checkpoint,
notification, promotion, automatic retry or production caller. A separate
wrapper records durable copy intents without clearing them.
"""
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import stat

from app.sqlite_isolated_lifecycle_runner import isolated_runner_lock
from app.sqlite_title_identity import validate_title_folder
from app.sqlite_operation_coordinator import INTENTS_KEY, SQLiteOperationCoordinator
from app.sqlite_audit_session import RevisionedAuditSession
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
    """Primitive-only fixture tool; no intent or lifecycle state changes."""
    return _stage_copy(root=root, title_folder=title_folder, operation_id=operation_id)


def stage_disposable_copy_with_intent(*, root, title_folder, media_key, operation_id,
                                    fault_at=None):
    """Durable copy rehearsal; always retains source and pending intent."""
    return _stage_copy(root=root, title_folder=title_folder, media_key=media_key,
                       operation_id=operation_id, persist_intent=True, fault_at=fault_at)


def stage_planned_disposable_copy(*, root, title_folder, media_key, operation_id,
                                  planned_move, destination_stage="holding"):
    """Bind source-retaining staging to a caller-supplied advisory candidate.

    This is planner parity, not independent Jellyfin freshness verification.
    """
    from app.sqlite_disposable_planned_executor import validate_disposable_move_candidate
    bundle = deepcopy(planned_move)
    if destination_stage not in ("holding", "keep"):
        raise ValueError("Unsupported copy candidate destination")
    validate_disposable_move_candidate(planned_move=bundle, media_key=media_key,
                                      source_stage="transient", destination_stage=destination_stage)
    if (not isinstance(bundle.get("now"), datetime) or bundle["now"].tzinfo is not None
            or bundle["now"] > datetime.now()):
        raise ValueError("Naive nonfuture advisory plan time required")
    return _stage_copy(root=root, title_folder=title_folder, media_key=media_key,
                       operation_id=operation_id, persist_intent=True,
                       planned_move=bundle, planned_destination=destination_stage)


def _stage_copy(*, root, title_folder, operation_id, media_key=None,
                persist_intent=False, fault_at=None, planned_move=None, planned_destination=None,
                _held_binding=None, _before_intent_review=None, _before_intent_check=None,
                _refresh_after_hash=None):
    """Create an exclusive hidden staged copy; retain source and tracking state.

    Requires trusted local transport primitives (exclusive create, fsync, reads).
    Errors preserve any partial staging for inspection. Never overwrite/resume.
    """
    root = Path(root)
    folder = validate_title_folder(title_folder)
    operation = validate_title_folder(operation_id)
    if persist_intent and media_key not in (folder, "TV/" + folder):
        raise ValueError("Copy folder and tracking key mismatch")
    if fault_at not in (None, "after_intent", "after_copy", "after_verified_checkpoint"):
        raise ValueError("Invalid copy rehearsal fault boundary")
    with (isolated_runner_lock(root) if _held_binding is None else nullcontext(_held_binding)) as verify_binding:
        verify_binding()
        session = RevisionedAuditSession(GuardedSQLiteStateStore(root / "state.db"))
        state, _ = session.read_verified_snapshot()
        if INTENTS_KEY in state:
            raise RuntimeError("Unresolved operation; copy staging stopped")
        if planned_move is not None and session.revision != planned_move["plan"]["source_revision"]:
            raise RuntimeError("Stale copy plan revision; staging stopped")
        source_parent = root / "transient"
        if source_parent.is_symlink() or not source_parent.is_dir():
            raise RuntimeError("Safe disposable source stage required")
        source_path = source_parent / folder
        if source_path.resolve() != source_path:
            raise RuntimeError("Source aliases refused")
        root_fd = os.open(root, FLAGS)
        try:
            verify_binding()
            source_parent_fd = os.open("transient", FLAGS, dir_fd=root_fd)
        except BaseException:
            os.close(root_fd)
            raise
        try:
            source_fd = os.open(folder, FLAGS, dir_fd=source_parent_fd)
        except BaseException:
            os.close(source_parent_fd)
            os.close(root_fd)
            raise
        stage_parent_fd = stage_fd = None
        try:
            original_source = os.fstat(source_fd)
            original_source_parent = os.fstat(source_parent_fd)

            def verify_source_binding(boundary):
                current_parent = os.stat("transient", dir_fd=root_fd, follow_symlinks=False)
                current_source = os.stat(folder, dir_fd=source_parent_fd, follow_symlinks=False)
                if (not stat.S_ISDIR(current_parent.st_mode)
                        or (current_parent.st_dev, current_parent.st_ino)
                        != (original_source_parent.st_dev, original_source_parent.st_ino)
                        or source_path.resolve() != source_path
                        or (current_source.st_dev, current_source.st_ino)
                        != (original_source.st_dev, original_source.st_ino)):
                    raise RuntimeError("Copy source binding changed " + boundary)

            verify_source_binding("before observation")
            before, identities = _manifest(source_fd)
            stage_parent = root / ".sqlite_copy_staging"
            staged_path = stage_parent / operation
            if staged_path.exists() or staged_path.is_symlink():
                raise FileExistsError("Copy staging slot occupied")
            if persist_intent:
                if (media_key not in state["first_seen"]
                        or any(media_key in state[section] for section in ("queued", "in_removal", "keep_seen"))):
                    raise RuntimeError("Copy source tracking clock missing or conflicting")
                manifest_digest = hashlib.sha256(json.dumps(
                    before, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()
                if planned_move is not None:
                    from app.sqlite_stale_plan_review import review_plan_again
                    try:
                        review = review_plan_again(
                            database=root / "state.db", original_plan=planned_move["plan"],
                            now=planned_move["now"], thresholds=planned_move["thresholds"],
                            signals_by_key=planned_move["signals_by_key"],
                            favorites_trigger_keep=planned_move.get("favorites_trigger_keep", True))
                    except KeyError as exc:
                        raise ValueError("Incomplete copy advisory bundle") from exc
                    if review["status"] != "unchanged_advisory_only":
                        raise RuntimeError("Copy advisory plan changed; staging stopped")
                    session.read_verified_snapshot()
                plan_binding = {}
                if planned_move is not None:
                    if planned_move["now"] < datetime.fromisoformat(state["first_seen"][media_key]):
                        raise RuntimeError("Copy observation predates source clock")
                    plan_binding = {"plan_binding": {
                        "source_revision": session.revision, "source_stage": "transient",
                        "destination_stage": planned_destination,
                        "observed_at": planned_move["now"].isoformat()}}
                if _before_intent_review is not None:
                    _before_intent_review()
                # Advisory review can be slow. Do not persist an intent against
                # the earlier source observation if an external writer changed it.
                current_manifest, current_identities = _manifest(source_fd)
                if before != current_manifest or identities != current_identities:
                    raise RuntimeError("Copy source changed before intent")
                if _refresh_after_hash is not None:
                    from app.sqlite_copy_live_verification import refresh_hashed_copy
                    refresh_hashed_copy(trees=((source_fd, current_identities),),
                                        refresh=_refresh_after_hash,
                                        check_window=_before_intent_check)
                verify_source_binding("before intent")
                verify_binding()
                session.read_verified_snapshot()
                if _before_intent_check is not None:
                    _before_intent_check()
                SQLiteOperationCoordinator(session).begin(operation, "copy_stage", {
                    "media_key": media_key, "source": str(source_path),
                    "staging": str(staged_path), "copy_phase": "prepared",
                    "source_timestamp": state["first_seen"][media_key],
                    "manifest_sha256": manifest_digest, **plan_binding,
                })
                verify_binding()
                if fault_at == "after_intent":
                    raise RuntimeError("Injected copy crash after intent")
            try:
                os.mkdir(".sqlite_copy_staging", mode=0o700, dir_fd=root_fd)
            except FileExistsError:
                pass
            stage_parent_stat = os.stat(".sqlite_copy_staging", dir_fd=root_fd, follow_symlinks=False)
            if not stat.S_ISDIR(stage_parent_stat.st_mode):
                raise RuntimeError("Safe private staging directory required")
            stage_parent_fd = os.open(".sqlite_copy_staging", FLAGS, dir_fd=root_fd)
            original_stage_parent = os.fstat(stage_parent_fd)
            os.mkdir(operation, mode=0o700, dir_fd=stage_parent_fd)
            stage_fd = os.open(operation, FLAGS, dir_fd=stage_parent_fd)
            original_stage = os.fstat(stage_fd)
            verify_binding()
            verify_source_binding("before copying")
            _copy_tree(source_fd, stage_fd)
            if fault_at == "after_copy":
                raise RuntimeError("Injected copy crash after copy")
            verify_source_binding("after copying")
            after, after_identities = _manifest(source_fd)
            copied, _ = _manifest(stage_fd)
            if before != after or identities != after_identities or copied != before:
                raise CopyVerificationError(before, after, identities, after_identities, copied)
            verify_source_binding("after copying")
            stage_current = os.stat(operation, dir_fd=stage_parent_fd, follow_symlinks=False)
            if (stage_current.st_dev, stage_current.st_ino) != (original_stage.st_dev, original_stage.st_ino):
                raise RuntimeError("Copy path binding changed; source retained")
            parent_current = os.stat(".sqlite_copy_staging", dir_fd=root_fd, follow_symlinks=False)
            if (parent_current.st_dev, parent_current.st_ino) != (original_stage_parent.st_dev, original_stage_parent.st_ino):
                raise RuntimeError("Staging parent changed; source retained")
            os.fsync(stage_parent_fd)
            os.fsync(root_fd)
            verify_binding()
            verify_source_binding("before verified checkpoint")
            if persist_intent:
                session.read_verified_snapshot()
                intent = session.state[INTENTS_KEY]
                intent["details"]["copy_phase"] = "verified_source_retained"
                intent["phase"] = "applied_pending_reconciliation"
                session.checkpoint()
                if fault_at == "after_verified_checkpoint":
                    raise RuntimeError("Injected copy crash after verified checkpoint")
            result = {"status": "copy_verified_pending_review" if persist_intent else "staged_copy_verified", "source_retained": True,
                    "files_verified": sum(entry[0] == "file" for entry in before.values()),
                    "tracking_committed": False, "promotion_authorized": False,
                    "production_activation": "disabled"}
            if persist_intent:
                result["intent_persisted"] = True
                result["lifecycle_committed"] = False
            return result
        finally:
            if stage_fd is not None:
                os.close(stage_fd)
            if stage_parent_fd is not None:
                os.close(stage_parent_fd)
            os.close(source_fd)
            os.close(source_parent_fd)
            os.close(root_fd)
