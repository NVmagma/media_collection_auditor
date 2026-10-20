"""Read-only host-side Compose lab review; does not authorize lab writes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

from scripts.sqlite_lab_preflight import check_lab_environment


def verify_compose_layout(config: dict, lab: Path, checkout: Path,\n                          expected_image: str | None = None,\n                          expected_user: str | None = None) -> dict:
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
    if (service.get("security_opt") != ["no-new-privileges:true"]\n            or service.get("working_dir") != "/workspace"\n            or service.get("tmpfs") != ["/tmp:rw,nosuid,nodev,noexec,size=32m"]\n            or service.get("environment") != {\n                "PYTHONPATH": "/workspace",\n                "PYTHONDONTWRITEBYTECODE": "1",\n                "PYTHONNOUSERSITE": "1",\n            }\n            or service.get("user", expected_user) != expected_user\n            or service.get("image", expected_image) != expected_image):\n        raise RuntimeError("Compose runtime identity or security mismatch")\n    mounts = service.get("volumes")
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
    import os\n    values = os.environ\n    result = verify_compose_layout(\n        json.loads(completed.stdout), lab, checkout,\n        expected_image=values["SQLITE_LAB_IMAGE"],\n        expected_user=values["SQLITE_LAB_UID"] + ":" + values["SQLITE_LAB_GID"],\n    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
