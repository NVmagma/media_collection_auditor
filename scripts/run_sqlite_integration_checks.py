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
    "test_docker_runtime_context", "test_sqlite_copy_source_parent_binding",
    "test_sqlite_copy_live_verification",
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--basetemp", required=True, help="New absolute fixture directory inside a disposable lab")
    parser.add_argument("--full-suite", action="store_true",
                        help="Run all tests; requires Linux no-replace rename support for move regressions")
    parser.add_argument("--publication-supported", action="store_true",
                        help="Include actual publication crash tests; requires no-replace rename support")
    args = parser.parse_args(argv)
    base = Path(args.basetemp)
    if (not base.is_absolute() or base.resolve() != base or not base.parent.is_dir()
            or base.exists() or base.is_symlink()):
        parser.error("Fixture path must be new, absolute and without aliases; existing labs are never reused")
    repo = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.setdefault("WEB_SESSION_SECRET", secrets.token_urlsafe(32))
    targets = [str(repo / "tests")] if args.full_suite else [str(repo / "tests" / (name + ".py")) for name in TESTS]
    if not args.full_suite:
        publication = str(repo / "tests" / "test_sqlite_disposable_copy_publication.py")
        completion = str(repo / "tests" / "test_sqlite_disposable_copy_completion.py")
        if args.publication_supported:
            targets.extend((publication, completion))
        else:
            targets.extend(publication + "::" + name for name in (
                "test_unsupported_atomic_publication_retains_source_and_staging",
                "test_destination_is_never_overwritten",
                "test_publication_intent_crash_is_not_replayed",
                "test_actual_capability_either_publishes_or_preserves_prepared_copy",
                "test_changed_staged_bytes_do_not_create_publication_marker",
                "test_missing_plan_binding_is_not_permission_to_publish"))
            targets.extend(completion + "::" + name for name in (
                "test_real_capability_preserves_original_bytes_in_all_supported_outcomes",
                "test_changed_refresh_blocks_before_publication_and_quarantine",
                "test_invalid_queue_request_stops_before_copy_intent",
                "test_reused_retention_identifier_stops_before_publication",
                "test_transfer_renewal_requires_fresh_unchanged_bounded_observations",
                "test_checkpoint_delay_expires_before_directory_action[publication]"))
    return subprocess.run(
        [sys.executable, "-B", "-m", "pytest", "-p", "no:cacheprovider",
         "--basetemp=" + str(base), *targets,
         "-q", "--tb=short"], cwd=repo, env=env).returncode


if __name__ == "__main__":
    raise SystemExit(main())
