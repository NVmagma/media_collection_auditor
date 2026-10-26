#!/usr/bin/env python3
"""Create a new synthetic lab and rehearse migration plus advanced-state rollback."""
import argparse
import json
import sqlite3
import subprocess
from app.sqlite_disposable_cutover_rehearsal import rehearse_disposable_cutover


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="New absolute lab directory; must not exist")
    args = parser.parse_args(argv)
    try:
        report = rehearse_disposable_cutover(root=args.root)
    except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error, subprocess.SubprocessError):
        print(json.dumps({"status": "blocked", "reason": "disposable_rehearsal_failed",
                          "artifacts_retained": True, "authorization": "not_authorized",
                          "production_activation": "disabled", "production_restore_performed": False}))
        return 2
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
