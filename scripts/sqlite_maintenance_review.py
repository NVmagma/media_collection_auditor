#!/usr/bin/env python3
"""Read-only forensic report for an existing marked maintenance lab; no resume."""
import argparse
import json
import sqlite3

from app.sqlite_maintenance_review import review_disposable_maintenance


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    args = parser.parse_args(argv)
    try:
        report = review_disposable_maintenance(args.root)
    except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error):
        report = {"status": "blocked", "reason": "retained_fixture_review_unavailable",
                  "read_only": True, "automatic_action": "none", "resume_authorized": False,
                  "clearance_authorized": False, "production_authorized": False,
                  "production_activation": "disabled", "writer_exclusion_verified": False,
                  "restart_inhibition_verified": False}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("history_valid") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
