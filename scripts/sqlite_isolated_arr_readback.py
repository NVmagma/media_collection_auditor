#!/usr/bin/env python3
"""GET-only readback for a pending Arr intent in an existing marked lab."""
import argparse
import json
import os
import sqlite3

from app.sqlite_arr_outcome_http import inspect_isolated_arr_http


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    args = parser.parse_args(argv)
    try:
        report = inspect_isolated_arr_http(
            root=args.root, radarr_url=os.environ.get("RADARR_URL", ""),
            radarr_key=os.environ.get("RADARR_API_KEY", ""),
            sonarr_url=os.environ.get("SONARR_URL", ""), sonarr_key=os.environ.get("SONARR_API_KEY", ""))
    except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error):
        report = {"status": "blocked", "observation": "safe_arr_readback_unavailable",
                  "read_only": True, "retry_authorized": False, "clearance_authorized": False,
                  "authorization": "not_authorized", "production_activation": "disabled"}
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0 if report.get("observation") == "matching_record_unverified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
