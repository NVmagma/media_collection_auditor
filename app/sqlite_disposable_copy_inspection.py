"""Explicit, potentially expensive content inspection; never copy recovery."""
from contextlib import nullcontext
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path

from app.sqlite_disposable_copy_stage import FLAGS, _manifest
from app.sqlite_isolated_lifecycle_runner import isolated_runner_lock
from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_title_identity import validate_title_folder
from app.state_store import GuardedSQLiteStateStore


def _observe(root, parent_name, name, digest):
    # Open each component relative to held descriptors, refusing symlink parents.
    root_fd = os.open(root, FLAGS)
    parent_fd = child_fd = None
    try:
        parent_fd = os.open(parent_name, FLAGS, dir_fd=root_fd)
        child_fd = os.open(name, FLAGS, dir_fd=parent_fd)
        before, identities = _manifest(child_fd)
        after, after_identities = _manifest(child_fd)
        if before != after or identities != after_identities:
            return "changed_during_inspection"
        for fd, parent, component in ((parent_fd, root_fd, parent_name), (child_fd, parent_fd, name)):
            held = os.fstat(fd)
            current = os.stat(component, dir_fd=parent, follow_symlinks=False)
            if (held.st_dev, held.st_ino) != (current.st_dev, current.st_ino):
                return "changed_during_inspection"
        actual = hashlib.sha256(json.dumps(before, sort_keys=True, separators=(",", ":"),
                                          ensure_ascii=True).encode("ascii")).hexdigest()
        return "content_matches_unverified" if actual == digest else "content_mismatch"
    except FileNotFoundError:
        return "missing"
    except (OSError, RuntimeError):
        return "unavailable_or_unsafe"
    finally:
        for fd in (child_fd, parent_fd, root_fd):
            if fd is not None:
                os.close(fd)


def inspect_disposable_copy(*, root, _held_binding=None):
    """Read retained lab content without clearing intents or granting authority.

    Matching bytes cannot establish historical identity, writer exclusion, or
    Jellyfin protection freshness. This is unsuitable for routine API polling.
    """
    root = Path(root)
    with (isolated_runner_lock(root) if _held_binding is None else nullcontext(_held_binding)) as verify_binding:
        verify_binding()
        session = RevisionedAuditSession(GuardedSQLiteStateStore(root / "state.db"))
        state, revision = session.read_verified_snapshot()
        pending = state.get(INTENTS_KEY)
        if not isinstance(pending, dict) or pending.get("kind") != "copy_stage":
            raise RuntimeError("Pending copy required")
        details = pending.get("details")
        if (not isinstance(details, dict)
                or pending.get("phase") not in ("intent_recorded", "applied_pending_reconciliation")
                or (pending.get("phase"), details.get("copy_phase")) not in (
                    ("intent_recorded", "prepared"),
                    ("applied_pending_reconciliation", "verified_source_retained"))):
            raise RuntimeError("Pending copy invalid")
        operation = validate_title_folder(pending.get("id"))
        key = details.get("media_key")
        if not isinstance(key, str):
            raise RuntimeError("Pending copy key invalid")
        folder = validate_title_folder(key[3:] if key.startswith("TV/") else key)
        digest = details.get("manifest_sha256")
        if (details.get("source") != str(root / "transient" / folder)
                or details.get("staging") != str(root / ".sqlite_copy_staging" / operation)
                or not isinstance(digest, str) or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
                or key not in state["first_seen"]
                or not isinstance(details.get("source_timestamp"), str)
                or state["first_seen"].get(key) != details.get("source_timestamp")
                or any(key in state[section] for section in ("queued", "in_removal", "keep_seen"))):
            raise RuntimeError("Pending copy binding invalid")
        plan_binding = details.get("plan_binding")
        if "plan_binding" in details:
            if (not isinstance(plan_binding, dict)
                    or set(plan_binding) != {"source_revision", "source_stage", "destination_stage", "observed_at"}
                    or type(plan_binding.get("source_revision")) is not int
                    or not 0 <= plan_binding["source_revision"] < revision
                    or plan_binding.get("source_stage") != "transient"
                    or plan_binding.get("destination_stage") not in ("holding", "keep")):
                raise RuntimeError("Pending copy plan binding invalid")
            try:
                observed = datetime.fromisoformat(plan_binding["observed_at"])
                source_time = datetime.fromisoformat(details["source_timestamp"])
                if (observed.tzinfo is not None or source_time.tzinfo is not None
                        or observed < source_time or observed > datetime.now()):
                    raise ValueError("Invalid plan time")
            except (ValueError, TypeError):
                raise RuntimeError("Pending copy plan time invalid") from None
        publication = details.get("publication")
        if "publication" in details:
            if (not isinstance(publication, dict) or plan_binding is None
                    or set(publication) != {"phase", "destination_stage", "destination"}
                    or publication.get("phase") not in ("prepared", "published_source_retained")
                    or publication.get("destination_stage") != plan_binding["destination_stage"]
                    or publication.get("destination") != str(root / plan_binding["destination_stage"] / folder)):
                raise RuntimeError("Pending copy publication binding invalid")
        retirement = details.get("retirement")
        if "retirement" in details:
            if (not isinstance(retirement, dict) or publication is None
                    or retirement.get("phase") != "prepared"
                    or retirement.get("retained_source") != str(root / ".sqlite_retained_sources" / operation)):
                raise RuntimeError("Pending copy retirement binding invalid")
        source = _observe(root, "transient", folder, digest)
        staging = _observe(root, ".sqlite_copy_staging", operation, digest)
        published = (_observe(root, plan_binding["destination_stage"], folder, digest)
                     if publication is not None else "not_requested")
        retained = (_observe(root, ".sqlite_retained_sources", operation, digest)
                    if retirement is not None else "not_requested")
        verify_binding()
        session.read_verified_snapshot()
        return {"status": "blocked", "revision": revision, "copy_phase": details["copy_phase"],
                "source_status": source, "staging_status": staging, "read_only": True,
                "publication_phase": publication["phase"] if publication else None,
                "published_status": published, "retained_source_status": retained,
                "plan_binding_available": plan_binding is not None,
                "proposed_destination_stage": plan_binding["destination_stage"] if plan_binding else None,
                "recovery_authorized": False, "promotion_authorized": False,
                "production_activation": "disabled", "storage_authority": "json"}
