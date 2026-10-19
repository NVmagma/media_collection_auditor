"""Compare advisory mount observations without asserting shared storage identity.

Container mount namespaces are independent. Even identical Linux mount IDs
or device fields do not establish that services see the same media object.
"""
from __future__ import annotations

from typing import Any


def inspect_cross_container_mount_evidence(observations: Any) -> dict[str, str]:
    blocked = {
        "status": "blocked",
        "authorization": "not_authorized",
        "shared_mount_identity": "unverified",
        "reconciliation": "disabled",
    }
    if not isinstance(observations, dict) or set(observations) != {
        "auditor", "jellyfin", "arr"
    }:
        return {**blocked, "reason": "service_observations_missing"}
    for name in ("auditor", "jellyfin", "arr"):
        item = observations[name]
        if (not isinstance(item, dict)
                or set(item) != {"status", "authorization", "mount_identity", "reason"}
                or item.get("status") != "blocked"
                or item.get("authorization") != "not_authorized"
                or item.get("mount_identity") != "local_namespace_observed_unverified"
                or item.get("reason") != "cross_container_identity_not_established"):
            return {**blocked, "reason": "service_observation_unverified"}
    return {**blocked, "reason": "independent_mount_identity_not_established"}
