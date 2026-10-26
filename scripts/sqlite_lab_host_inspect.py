"""Read-only host-side Compose lab review; does not authorize lab writes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

from scripts.sqlite_lab_preflight import check_lab_environment


def verify_compose_layout(config: dict, lab: Path, checkout: Path,
                          expected_image: str | None = None,
                          expected_user: str | None = None) -> dict:
    """Fail closed on unexpected services, mounts, privileges or networking."""
    services = config.get("services")
    if not isinstance(services, dict) or set(services) != {"sqlite-lab"}:
        raise RuntimeError("Unexpected Compose services")
    service = services["sqlite-lab"]
    if (service.get("network_mode") != "none" or service.get("read_only") is not True
            or service.get("privileged", False)
            or service.get("cap_drop") != ["ALL"]
            or service.get("entrypoint") != ["python"]
            or service.get("ports")
            or service.get("devices")):
        raise RuntimeError("Compose isolation settings mismatch")
    if (service.get("security_opt") != ["no-new-privileges:true"]
            or service.get("working_dir") != "/workspace"
            or service.get("tmpfs") != ["/tmp:rw,nosuid,nodev,noexec,size=32m"]
            or service.get("environment") != {
                "PYTHONPATH": "/workspace",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONNOUSERSITE": "1",
            }
            or service.get("user", expected_user) != expected_user
            or service.get("image", expected_image) != expected_image):
        raise RuntimeError("Compose runtime identity or security mismatch")
    mounts = service.get("volumes")
    if not isinstance(mounts, list) or len(mounts) != 2:
        raise RuntimeError("Unexpected Compose mount count")
    expected = {"/lab": (lab, False), "/workspace": (checkout, True)}
    observed = set()
    for mount in mounts:
        if not isinstance(mount, dict):
            raise RuntimeError("Invalid Compose mount")
        target = mount.get("target")
        if target not in expected or target in observed or mount.get("type") != "bind":
            raise RuntimeError("Unexpected Compose bind mount")
        observed.add(target)
        source, readonly = expected[target]
        if (mount.get("source") != str(source)
                or mount.get("read_only", False) is not readonly
                or mount.get("bind", {}).get("create_host_path", False)):
            raise RuntimeError("Compose bind source or mode mismatch")
    if observed != set(expected):
        raise RuntimeError("Missing expected Compose mount")
    return {"status": "review_required", "authorization": "not_authorized",
            "lab": str(lab), "checkout": str(checkout),
            "mounts": sorted(observed)}



def compare_unraid_mount_evidence(
    docker_mounts: list, probe: dict, lab: Path, checkout: Path,
) -> dict[str, str]:
    """Read-only comparison of snapshots; never grants write authorization.

    Caller must independently obtain Docker inspect and container mount probe.
    These snapshots are not cryptographically authenticated or atomic.
    """
    blocked = {"status": "blocked", "authorization": "not_authorized"}
    expected = {"/lab": (str(lab), True),
                "/workspace": (str(checkout), False)}
    try:
        if (not isinstance(docker_mounts, list) or len(docker_mounts) != 2
                or not isinstance(probe, dict)
                or lab.name != "sqlite_lab_test"
                or checkout.name != "sqlite_lab_checkout"
                or str(lab) != "/mnt/user/sqlite_lab_test"
                or str(checkout) != "/mnt/user/sqlite_lab_checkout"):
            raise ValueError("unexpected lab identity")
        seen = set()
        for mount in docker_mounts:
            target = mount["Destination"]
            if (target not in expected or target in seen
                    or mount["Type"] != "bind"
                    or mount["Source"] != expected[target][0]
                    or mount["RW"] is not expected[target][1]):
                raise ValueError("unexpected Docker mount")
            seen.add(target)
        if seen != set(expected):
            raise ValueError("missing Docker mount")
        records = probe["lab_mounts"]
        if (probe["lab_mount_count"] != 1 or len(records) != 1
                or probe["authorization"] != "not_authorized"
                or probe["production_media_inspected"] is not False
                or probe["status"] != "blocked"
                or probe["reason"] != "lab_mount_root_unverified"):
            raise ValueError("unexpected probe verdict")
        record = records[0]
        if (record["target"] != "/lab"
                or record["root"] != "/sqlite_lab_test"
                or record["filesystem"] != "fuse.shfs"
                or record["read_only"] is not False):
            raise ValueError("unexpected mountinfo")
    except (KeyError, TypeError, ValueError, AttributeError):
        return {**blocked, "reason": "mount_evidence_mismatch"}
    return {"status": "review_required", "authorization": "not_authorized",
            "reason": "untrusted_snapshots_match"}

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compose", default="docker-compose.sqlite-lab.yaml")
    args = parser.parse_args()
    lab = check_lab_environment()
    checkout = Path.cwd().resolve(strict=True)
    compose = (checkout / args.compose).resolve(strict=True)
    if compose.parent != checkout:
        raise SystemExit("Compose file must be inside checkout root")
    completed = subprocess.run(
        ["docker", "compose", "-f", str(compose), "--profile", "sqlite-lab",
         "config", "--format", "json"], check=True, capture_output=True, text=True,
        timeout=30,
    )
    import os
    values = os.environ
    result = verify_compose_layout(
        json.loads(completed.stdout), lab, checkout,
        expected_image=values["SQLITE_LAB_IMAGE"],
        expected_user=values["SQLITE_LAB_UID"] + ":" + values["SQLITE_LAB_GID"],
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
