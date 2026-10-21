"""No-overwrite publication of a verified LAB copy; source always retained."""
from contextlib import ExitStack, nullcontext
import hashlib
import json
import os
from pathlib import Path

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_disposable_copy_inspection import inspect_disposable_copy
from app.sqlite_disposable_copy_stage import FLAGS, _manifest
from app.sqlite_isolated_lifecycle_runner import isolated_runner_lock
from app.sqlite_noreplace_rename import rename_directory_noreplace_at
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.state_store import GuardedSQLiteStateStore


def _digest(manifest):
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode("ascii")).hexdigest()


def publish_disposable_copy(*, root, fault_at=None):
    return _publish_disposable_copy(root=root, fault_at=fault_at)


def _publish_disposable_copy(*, root, fault_at=None, _held_binding=None, _completion=None):
    """Publish once, leaving source, clocks, queue and intent for manual review.

    Requires a valid plan-bound copy intent and actual atomic no-replace rename.
    This optional capability is not a portable fallback or a complete move.
    Any publication marker, including an uncertain one, prevents another attempt.
    """
    if fault_at not in (None, "after_intent", "after_publication", "after_checkpoint"):
        raise ValueError("Invalid publication rehearsal fault boundary")
    root = Path(root)
    reviewed = inspect_disposable_copy(root=root, _held_binding=_held_binding)
    with (isolated_runner_lock(root) if _held_binding is None else nullcontext(_held_binding)) as verify_root:
        verify_root()
        session = RevisionedAuditSession(GuardedSQLiteStateStore(root / "state.db"))
        state, revision = session.read_verified_snapshot()
        pending = state[INTENTS_KEY]
        details = pending["details"]
        if "publication" in details:
            raise RuntimeError("Publication already attempted; manual review required")
        if (revision != reviewed["revision"] or not reviewed["plan_binding_available"]
                or reviewed["copy_phase"] != "verified_source_retained"
                or reviewed["source_status"] != "content_matches_unverified"
                or reviewed["staging_status"] != "content_matches_unverified"):
            raise RuntimeError("Verified plan-bound retained copy required")
        destination = reviewed["proposed_destination_stage"]
        operation = pending["id"]
        key = details["media_key"]
        folder = key[3:] if key.startswith("TV/") else key
        digest = details["manifest_sha256"]
        if _completion is not None:
            from app.sqlite_disposable_copy_completion import validate_completion
            validate_completion(state, details, folder, destination, _completion)
            _completion["refresh"]()
        with ExitStack() as stack:
            def opening(name, parent=None):
                fd = os.open(name, FLAGS, **({"dir_fd": parent} if parent is not None else {}))
                stack.callback(os.close, fd)
                return fd
            root_fd = opening(root)
            verify_root()
            parents = {name: opening(name, root_fd)
                       for name in ("transient", ".sqlite_copy_staging", destination)}
            parent_ids = {name: (os.fstat(fd).st_dev, os.fstat(fd).st_ino) for name, fd in parents.items()}
            source_fd = opening(folder, parents["transient"])
            copy_fd = opening(operation, parents[".sqlite_copy_staging"])
            source_id = (os.fstat(source_fd).st_dev, os.fstat(source_fd).st_ino)
            copy_id = (os.fstat(copy_fd).st_dev, os.fstat(copy_fd).st_ino)

            def verify_bindings(published=False, source_retired=False):
                verify_root()
                for name, identity in parent_ids.items():
                    current = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
                    if (current.st_dev, current.st_ino) != identity:
                        raise RuntimeError("Publication parent binding changed")
                if not source_retired:
                    current = os.stat(folder, dir_fd=parents["transient"], follow_symlinks=False)
                    if (current.st_dev, current.st_ino) != source_id:
                        raise RuntimeError("Publication source binding changed")
                else:
                    try:
                        os.stat(folder, dir_fd=parents["transient"], follow_symlinks=False)
                    except FileNotFoundError:
                        pass
                    else:
                        raise RuntimeError("Retired source entry reappeared")
                parent, name = (parents[destination], folder) if published else (parents[".sqlite_copy_staging"], operation)
                current = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if (current.st_dev, current.st_ino) != copy_id:
                    raise RuntimeError("Publication copy binding changed")

            verify_bindings()
            source_manifest, source_metadata = _manifest(source_fd)
            copy_manifest, _ = _manifest(copy_fd)
            if _digest(source_manifest) != digest or _digest(copy_manifest) != digest:
                raise RuntimeError("Publication content differs from recorded copy")
            for stage in ("holding", "keep", "removal"):
                stage_fd = parents.get(stage)
                if stage_fd is None:
                    stage_fd = opening(stage, root_fd)
                try:
                    os.stat(folder, dir_fd=stage_fd, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                raise RuntimeError("Publication destination already occupied or ambiguous")
            verify_bindings()
            session.read_verified_snapshot()
            details = session.state[INTENTS_KEY]["details"]
            details["publication"] = {"phase": "prepared", "destination_stage": destination,
                                      "destination": str(root / destination / folder)}
            session.checkpoint()
            if fault_at == "after_intent":
                raise RuntimeError("Injected publication crash after intent")
            verify_bindings()
            rename_directory_noreplace_at(parents[".sqlite_copy_staging"], operation,
                                          parents[destination], folder)
            if fault_at == "after_publication":
                raise RuntimeError("Injected publication crash after publication")
            verify_bindings(published=True)
            source_after, metadata_after = _manifest(source_fd)
            copy_after, _ = _manifest(copy_fd)
            if (source_after != source_manifest or metadata_after != source_metadata
                    or copy_after != copy_manifest):
                raise RuntimeError("Publication content changed; source retained")
            for fd in (parents[".sqlite_copy_staging"], parents[destination], root_fd):
                os.fsync(fd)
            verify_bindings(published=True)
            session.read_verified_snapshot()
            session.state[INTENTS_KEY]["details"]["publication"]["phase"] = "published_source_retained"
            session.checkpoint()
            if fault_at == "after_checkpoint":
                raise RuntimeError("Injected publication crash after checkpoint")
            if _completion is not None:
                from app.sqlite_disposable_copy_completion import complete_live_copy
                return complete_live_copy(root=root, root_fd=root_fd, parents=parents,
                    source_fd=source_fd, copy_fd=copy_fd, source_identity=source_id,
                    operation=operation, key=key, folder=folder, destination=destination,
                    digest=digest, session=session,
                    verify_published=lambda **kwargs: verify_bindings(published=True, **kwargs), config=_completion)
            return {"status": "published_source_retained_pending_review", "source_retained": True,
                    "lifecycle_committed": False, "intent_cleared": False, "retry_authorized": False,
                    "production_activation": "disabled", "authorization": "not_authorized"}
