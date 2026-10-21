"""In-process completion rehearsal; original bytes remain in private quarantine.

Never a restart recovery entry point. Called only while publication's original
source/copy descriptors and the marked-lab lock are still held.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os

from app.sqlite_arr_queue_plan import planned_arr_queue_entry
from app.sqlite_disposable_copy_stage import FLAGS, _manifest
from app.sqlite_noreplace_rename import rename_directory_noreplace_at
from app.sqlite_operation_coordinator import INTENTS_KEY

RETAINED_KEY = "sqlite_retained_sources"


def validate_completion(state, details, folder, destination, config):
    if config.get("fault_at") not in (None, "after_retirement_intent", "after_source_quarantine", "after_completion_checkpoint"):
        raise ValueError("Invalid completion fault boundary")
    observed = config["observed_at"]
    key = details["media_key"]
    if (not isinstance(observed, datetime) or observed.tzinfo is not None
            or observed > datetime.now()
            or observed < datetime.fromisoformat(details["source_timestamp"])
            or not callable(config["refresh"]) or not callable(config["check_window"])):
        raise ValueError("Bound observation and fresh collection callbacks required")
    retained = state.get(RETAINED_KEY, {})
    if not isinstance(retained, dict):
        raise RuntimeError("Retained source ledger invalid")
    if state[INTENTS_KEY]["id"] in retained:
        raise RuntimeError("Retained source operation already recorded")
    if key in state["arr_sync_pending"]:
        raise RuntimeError("Existing Arr queue blocks copy completion")
    request = deepcopy(config.get("arr_sync_request"))
    queue_entry = None if request is None else planned_arr_queue_entry(
        request=request, media_key=key, title_folder=folder, destination_stage=destination)
    return queue_entry


def complete_live_copy(*, root, root_fd, parents, source_fd, copy_fd,
                       source_identity, operation, key, folder, destination,
                       digest, session, verify_published, config):
    """Quarantine original with a live witness, then one atomic state checkpoint."""
    fault = config.get("fault_at")
    if fault not in (None, "after_retirement_intent", "after_source_quarantine", "after_completion_checkpoint"):
        raise ValueError("Invalid completion fault boundary")
    details = session.state[INTENTS_KEY]["details"]
    queue_entry = validate_completion(session.state, details, folder, destination, config)
    if operation in session.state.get(RETAINED_KEY, {}):
        raise RuntimeError("Retained source operation already recorded")
    archive_name = ".sqlite_retained_sources"
    try:
        os.mkdir(archive_name, mode=0o700, dir_fd=root_fd)
    except FileExistsError:
        pass
    archive_fd = os.open(archive_name, FLAGS, dir_fd=root_fd)
    try:
        archive_stat = os.fstat(archive_fd)
        def verify_archive():
            current = os.stat(archive_name, dir_fd=root_fd, follow_symlinks=False)
            if (current.st_dev, current.st_ino) != (archive_stat.st_dev, archive_stat.st_ino):
                raise RuntimeError("Retained source parent binding changed")
        try:
            os.stat(operation, dir_fd=archive_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise RuntimeError("Retained source slot occupied")
        config["refresh"]()
        verify_published()
        verify_archive()
        before, metadata = _manifest(source_fd)
        copied, _ = _manifest(copy_fd)
        actual_digest = hashlib.sha256(json.dumps(before, sort_keys=True, separators=(",", ":"),
                                                  ensure_ascii=True).encode("ascii")).hexdigest()
        if before != copied or actual_digest != digest:
            raise RuntimeError("Source and published copy differ before quarantine")
        config["check_window"]()
        retirement = {"phase": "prepared", "retained_source": str(root / archive_name / operation),
                      "observed_at": config["observed_at"].isoformat(), "arr_queue_entry": queue_entry}
        session.read_verified_snapshot()
        session.state[INTENTS_KEY]["details"]["retirement"] = retirement
        session.checkpoint()
        if fault == "after_retirement_intent":
            raise RuntimeError("Injected completion crash after retirement intent")
        verify_published()
        verify_archive()
        config["check_window"]()
        rename_directory_noreplace_at(parents["transient"], folder, archive_fd, operation)
        if fault == "after_source_quarantine":
            raise RuntimeError("Injected completion crash after source quarantine")
        # Source path must be absent. A recreated entry makes the outcome ambiguous.
        try:
            os.stat(folder, dir_fd=parents["transient"], follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise RuntimeError("Source entry reappeared during quarantine")
        held = os.stat(operation, dir_fd=archive_fd, follow_symlinks=False)
        if (held.st_dev, held.st_ino) != source_identity:
            raise RuntimeError("Quarantined source does not match live witness")
        after, after_metadata = _manifest(source_fd)
        published, _ = _manifest(copy_fd)
        # Our directory rename can change the root ctime, but not its contents
        # or the metadata of entries within it.
        stable_metadata = {k: v for k, v in metadata.items() if k}
        stable_after = {k: v for k, v in after_metadata.items() if k}
        if (after != before or published != before or stable_metadata != stable_after
                or metadata[""][:-1] != after_metadata[""][:-1]):
            raise RuntimeError("Retained content changed; completion blocked")
        for fd in (archive_fd, parents["transient"], parents[destination], root_fd):
            os.fsync(fd)
        verify_archive()
        verify_published(source_retired=True)
        retained_now = os.stat(operation, dir_fd=archive_fd, follow_symlinks=False)
        if (retained_now.st_dev, retained_now.st_ino) != source_identity:
            raise RuntimeError("Retained source changed before completion checkpoint")
        config["check_window"]()
        for stage in ("holding", "keep", "removal"):
            if stage == destination:
                continue
            stage_fd = os.open(stage, FLAGS, dir_fd=root_fd)
            try:
                try:
                    os.stat(folder, dir_fd=stage_fd, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise RuntimeError("Ambiguous lifecycle destination before completion")
            finally:
                os.close(stage_fd)
        session.read_verified_snapshot()
        state = session.state
        if state["first_seen"].get(key) != details["source_timestamp"]:
            raise RuntimeError("Copy completion clock binding changed")
        state["first_seen"].pop(key)
        state["queued" if destination == "holding" else "keep_seen"][key] = retirement["observed_at"]
        if queue_entry is not None:
            state["arr_sync_pending"][key] = queue_entry
        state.setdefault(RETAINED_KEY, {})[operation] = {
            "media_key": key, "retained_source": retirement["retained_source"],
            "destination": str(root / destination / folder), "manifest_sha256": digest,
            "completed_at": retirement["observed_at"]}
        state.pop(INTENTS_KEY)
        session.checkpoint()
        if fault == "after_completion_checkpoint":
            raise RuntimeError("Injected completion crash after checkpoint")
        return {"status": "disposable_copy_reconciled_source_quarantined", "original_bytes_retained": True,
                "lifecycle_committed": True, "intent_cleared": True, "permanent_deletion_performed": False,
                "production_activation": "disabled", "recovery_authorized": False, "authorization": "not_authorized"}
    finally:
        os.close(archive_fd)
