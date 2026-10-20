#!/usr/bin/env python3
"""Inspect an existing disposable copy intent; never resume or clear it.

Run from the checkout with PYTHONPATH=. and --root pointing to a marked lab.
Content hashing may read all source/staging bytes. The cooperating-runner lock
requires a writable lab mount; inspection changes neither media nor SQLite state.
A successful diagnostic command still reports blocked recovery authority.
"""
import argparse
import json
import sqlite3

from app.sqlite_disposable_copy_inspection import inspect_disposable_copy


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="Existing marked disposable lab root")
    args = parser.parse_args(argv)
    try:
        report = inspect_disposable_copy(root=args.root)
    except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error):
        # Paths, title names, hashes and arbitrary exception text stay private.
        report = {"status": "inspection_failed", "blocker": "safe_copy_inspection_unavailable",
                  "read_only": True, "recovery_authorized": False,
                  "promotion_authorized": False, "production_activation": "disabled",
                  "storage_authority": "json"}
        print(json.dumps(report, sort_keys=True, indent=2))
        return 2
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
