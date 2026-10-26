"""Offline-only CLI for experimental SQLite recovery status.

Usage: python -m app.sqlite_recovery_cli --database /path/to/experimental.db

This command never connects to Jellyfin/Arr, mutates state, or accepts
credentials. It does not activate SQLite as the production state backend.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from app.sqlite_recovery_report import inspect_pending_recovery_status

ERRORS = {
    "Pending recovery operation invalid": "invalid_pending_operation",
    "SQLite recovery session is stale": "concurrent_state_change",
    "SQLite session invalid after failed checkpoint; reopen required": "session_invalid",
}


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only experimental SQLite recovery status"
    )
    parser.add_argument("--database", required=True, type=Path,
                        help="Existing experimental SQLite database")
    args = parser.parse_args(argv)

    # Never create an empty SQLite database as a side effect of a typo.
    if not args.database.is_file():
        print(json.dumps({"status": "error", "reason": "database_unavailable"}))
        return 2
    try:
        report = inspect_pending_recovery_status(args.database)
    except Exception as exc:
        # Do not echo exception strings: they may include sensitive paths,
        # database content, or configuration values.
        reason = ERRORS.get(str(exc), "inspection_failed")
        print(json.dumps({"status": "error", "reason": reason}))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(run())
