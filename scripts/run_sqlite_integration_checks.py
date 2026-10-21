#!/usr/bin/env python3
"""Consolidated disposable regressions; no builds, services or production mounts.

Requires installed project requirements and pytest. The fixture path MUST NOT
exist: pytest owns basetemp and may clear it, so never reuse a retained lab.
"""
import argparse
import os
from pathlib import Path
import secrets
import subprocess
import sys

TESTS = (
    "test_sqlite_disposable_cutover_rehearsal", "test_sqlite_cutover_process_lock",
    "test_sqlite_lock", "test_sqlite_migration", "test_sqlite_migration_interruptions",
    "test_sqlite_disposable_rollback", "test_sqlite_rollback_json_restart",
    "test_sqlite_recovery_json_rollback", "test_sqlite_production_cutover_guard",
    "test_state_persistence", "test_sqlite_backend_gate", "test_sqlite_end_to_end",
    "test_sqlite_disposable_copy_stage", "test_sqlite_disposable_copy_intent",
    "test_sqlite_disposable_copy_inspection", "test_sqlite_disposable_copy_inspect_cli",
    "test_sqlite_planned_copy_stage", "test_sqlite_collected_copy_runner",
    "test_sqlite_collected_copy_series", "test_sqlite_isolated_arr_inspection",
    "test_sqlite_arr_outcome_http", "test_sqlite_isolated_arr_runner",
    "test_sqlite_arr_reconciliation", "test_sqlite_fetched_recovery", "test_sqlite_recovery_http",
    "test_sqlite_isolated_arr_readback_cli", "test_dashboard_tracking_snapshot",
    "test_dashboard_snapshot_parity", "test_dashboard_state_errors", "test_dashboard_inventory",
    "test_dashboard_lifecycle_visibility", "test_sqlite_dashboard_integration",
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--basetemp", required=True, help="New absolute fixture directory inside a disposable lab")
    args = parser.parse_args(argv)
    base = Path(args.basetemp)
    if (not base.is_absolute() or base.resolve() != base or not base.parent.is_dir()
            or base.exists() or base.is_symlink()):
        parser.error("Fixture path must be new, absolute and without aliases; existing labs are never reused")
    repo = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.setdefault("WEB_SESSION_SECRET", secrets.token_urlsafe(32))
    return subprocess.run(
        [sys.executable, "-B", "-m", "pytest", "-p", "no:cacheprovider",
         "--basetemp=" + str(base), *[str(repo / "tests" / (name + ".py")) for name in TESTS],
         "-q", "--tb=short"], cwd=repo, env=env).returncode


if __name__ == "__main__":
    raise SystemExit(main())
