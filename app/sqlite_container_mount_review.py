"""Advisory Docker snapshot review; lexical overlap is never writer exclusion."""
from pathlib import PurePosixPath


def _path(value):
    if (not isinstance(value, str) or not value.startswith("/") or value.startswith("//")
            or ".." in value.split("/") or "\x00" in value):
        raise ValueError("Absolute declared path required")
    return PurePosixPath(value)


def _overlap(left, right):
    return left == right or left in right.parents or right in left.parents


def _control_requirements(issues, *, running):
    required = set()
    if "writable_declared_media_mount" in issues or "writable_destination_overlap" in issues:
        required.update(("fence_media_write_routes", "inhibit_writer_start_or_restart"))
        if not running:
            required.add("keep_stopped_writer_fenced")
    if "read_only_media_mount_unverified" in issues:
        required.add("verify_read_only_media_routes")
    if "socket_access_requires_review" in issues:
        required.add("fence_administrative_api_routes")
    if issues.intersection({"privileged_container_review_required", "added_capabilities_review_required",
                            "host_pid_access_review_required", "device_access_review_required"}):
        required.add("review_elevated_host_access")
    if "non_bind_writer_requires_review" in issues:
        required.add("resolve_non_bind_storage_scope")
    return sorted(required)


def review_container_mounts(records, *, media_roots):
    roots = [_path(value) for value in media_roots]
    if not roots or len(set(roots)) != len(roots) or PurePosixPath("/") in roots:
        raise ValueError("Distinct specific media roots required")
    reviewed = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Selected container record required")
        for key in ("running", "paused", "privileged"):
            if type(record.get(key)) is not bool:
                raise ValueError("Selected container state invalid")
        if (not isinstance(record.get("name"), str) or not record["name"]
                or not isinstance(record.get("restart"), str)
                or not isinstance(record.get("pid_mode"), str)
                or type(record.get("device_count")) is not int or record["device_count"] < 0):
            raise ValueError("Selected container metadata invalid")
        caps = record.get("cap_add")
        if caps is not None and (not isinstance(caps, list) or not all(isinstance(c, str) for c in caps)):
            raise ValueError("Selected capability metadata invalid")
        if not isinstance(record.get("mounts"), list):
            raise ValueError("Selected mounts unavailable")
        mounts = []
        for item in record["mounts"]:
            if not isinstance(item, dict) or type(item.get("RW")) is not bool:
                raise ValueError("Selected mount invalid")
            destination = _path(item.get("Destination"))
            source = _path(item["Source"]) if item.get("Source") else None
            if not isinstance(item.get("Type"), str):
                raise ValueError("Selected mount type invalid")
            if item["Type"] == "bind" and source is None:
                raise ValueError("Selected bind source unavailable")
            mounts.append((item, source, destination))
        direct = [(index, destination) for index, (_, source, destination) in enumerate(mounts)
                  if source is not None and any(_overlap(source, root) for root in roots)]
        issues = set()
        observations = []
        if record["privileged"]:
            issues.add("privileged_container_review_required")
        if caps:
            issues.add("added_capabilities_review_required")
        if record["pid_mode"] == "host":
            issues.add("host_pid_access_review_required")
        if record["device_count"]:
            issues.add("device_access_review_required")
        for index, (item, source, destination) in enumerate(mounts):
            reasons = []
            if source is not None and any(_overlap(source, root) for root in roots):
                reasons.append("declared_media_source_overlap")
                issues.add("writable_declared_media_mount" if item["RW"] else "read_only_media_mount_unverified")
            if item["RW"] and any(index != other and _overlap(destination, media)
                                  for other, media in direct):
                reasons.append("writable_destination_overlap")
                issues.add("writable_destination_overlap")
            # Read-only access to a Docker socket still permits administrative
            # API calls. Other socket mounts need review too, not an allowlist.
            if any(str(path).endswith(".sock") for path in (source, destination) if path is not None):
                reasons.append("socket_access_requires_review")
                issues.add("socket_access_requires_review")
            if item["RW"] and item["Type"] != "bind":
                reasons.append("non_bind_writer_requires_review")
                issues.add("non_bind_writer_requires_review")
            if reasons:
                observations.append({"source": str(source) if source is not None else None,
                                     "destination": str(destination), "writable": item["RW"],
                                     "type": item["Type"], "reasons": reasons})
        if issues:
            reviewed.append({"name": record["name"], "running": record["running"],
                             "paused": record["paused"], "restart": record["restart"],
                             "issues": sorted(issues), "mounts": observations,
                             "control_requirements": _control_requirements(issues, running=record["running"])})
    return {"status": "review_required", "read_only": True, "containers_observed": len(records),
            "containers_requiring_review": reviewed, "declared_media_roots": [str(root) for root in roots],
            "path_resolution_verified": False, "snapshot_continuity_verified": False,
            "enforcement_supported": False,
            "writer_exclusion_verified": False, "restart_inhibition_verified": False,
            "production_authorized": False, "production_activation": "disabled",
            "automatic_action": "none", "blockers": ["snapshot_never_authorizes_enforcement",
                "physical_alias_resolution_unverified", "host_and_share_writers_unverified",
                "administrative_restart_controls_unverified"]}
