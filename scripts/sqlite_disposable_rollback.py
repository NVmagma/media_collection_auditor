#!/usr/bin/env python3
"""Export/inspect fresh private JSON candidates in an existing disposable lab.

No restore, cutover or activation command exists. Never use a production root.
"""
import argparse
import json
import sqlite3

from app.sqlite_disposable_rollback import (export_disposable_rollback_candidate,
                                          inspect_disposable_rollback_candidate)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("export", "inspect"))
    parser.add_argument("--root", required=True)
    parser.add_argument("--candidate-name", required=True,
                        help="New private rollback-candidate-*.json filename inside the lab")
    args = parser.parse_args(argv)
    action = (export_disposable_rollback_candidate if args.action == "export"
              else inspect_disposable_rollback_candidate)
    try:
        report = action(root=args.root, candidate_name=args.candidate_name)
    except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error):
        print(json.dumps({"status": "blocked", "reason": "safe_candidate_operation_unavailable",
                          "authorization": "not_authorized", "production_activation": "disabled",
                          "restore_performed": False, "media_actions_performed": False}, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0 if report["status"] == "matching_candidate_advisory_only" else 2


if __name__ == "__main__":
    raise SystemExit(main())
