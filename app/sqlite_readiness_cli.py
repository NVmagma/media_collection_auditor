"""Offline-only CLI for inspecting a JSON-to-SQLite migration.

Never creates files, activates SQLite, or performs media operations.
Run with: python -m app.sqlite_readiness_cli SOURCE BACKUP DATABASE
"""

from __future__ import annotations

import argparse
import json

from app.sqlite_readiness import inspect_sqlite_readiness


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only SQLite migration readiness")
    parser.add_argument("source_json")
    parser.add_argument("backup_json")
    parser.add_argument("database")
    args = parser.parse_args(argv)
    report = inspect_sqlite_readiness(
        args.source_json, args.backup_json, args.database
    )
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ready_for_isolated_review"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
