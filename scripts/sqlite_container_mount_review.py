#!/usr/bin/env python3
"""Review selected Docker JSON records from stdin; never access the Docker API."""
import argparse
import json
import sys

from app.sqlite_container_mount_review import DEFAULT_CONTROL_ROOTS, review_container_mounts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--media-root", action="append", required=True)
    parser.add_argument("--control-root", action="append",
                        help="Additional declared control socket/directory alias; never an access permit")
    args = parser.parse_args(argv)
    try:
        content = sys.stdin.buffer.read(1024 * 1024 + 1)
        if len(content) > 1024 * 1024:
            raise ValueError("Snapshot exceeds input bound")
        lines = [json.loads(line) for line in content.splitlines() if line.strip()]
        if not lines or lines[-1] != {"kind": "end"} or len(lines) > 501:
            raise ValueError("Incomplete selected snapshot")
        records = lines[:-1]
        if any(not isinstance(row, dict) or row.get("kind") != "container" for row in records):
            raise ValueError("Invalid selected snapshot")
        report = review_container_mounts(records, media_roots=args.media_root,
            control_roots=tuple(DEFAULT_CONTROL_ROOTS)+tuple(args.control_root or ()))
    except (ValueError, TypeError, KeyError, UnicodeError):
        report = {"status": "blocked", "reason": "selected_mount_snapshot_unavailable_or_invalid",
                  "read_only": True, "automatic_action": "none", "production_authorized": False,
                  "production_activation": "disabled", "writer_exclusion_verified": False}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "review_required" else 2


if __name__ == "__main__":
    raise SystemExit(main())
