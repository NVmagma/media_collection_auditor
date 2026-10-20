"""Read-only lab mount diagnostic; never grants permission to write.

Run only inside the isolated sqlite-lab Compose service. No paths are
created, moved, deleted or reconciled. The /lab mount remains untrusted.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.sqlite_lab_fixture_guard import inspect_lab_mount_boundaries


def inspect_lab_mount_report(mountinfo: str) -> dict[str, object]:
    """Report bounded mount facts without disclosing host mount sources."""
    verdict = inspect_lab_mount_boundaries(mountinfo)
    lab_records = []
    for line in mountinfo.splitlines():
        fields = line.split(" - ")
        if len(fields) != 2:
            continue
        left = fields[0].split()
        right = fields[1].split()
        if len(left) < 6 or len(right) < 3:
            continue
        mount_point = left[4]
        if mount_point == "/lab" or mount_point.startswith("/lab/"):
            lab_records.append({
                "target": mount_point,
                "root": left[3],
                "filesystem": right[0],
                "read_only": "ro" in left[5].split(","),
            })
    return {
        "status": verdict["status"],
        "reason": verdict["reason"],
        "authorization": "not_authorized",
        "lab_mounts": lab_records,
        "lab_mount_count": len(lab_records),
        "production_media_inspected": False,
    }


def main() -> None:
    report = inspect_lab_mount_report(Path("/proc/self/mountinfo").read_text())
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
