#!/usr/bin/env python3
"""Disposable Linux namespace-binding check; no NFS or production actions."""
import argparse
import json
from pathlib import Path
import sys
import time

from app.sqlite_disposable_maintenance_journal import (
    MaintenanceNetworkScopeChanged, advance_disposable_journal,
    create_disposable_journal, inspect_disposable_journal,
)

MARKER = b"DISPOSABLE MAINTENANCE SCOPE LAB\n"


def prepare(control):
    root = control / "maintenance-journal"
    create_disposable_journal(root, bind_linux_boot=True)
    advance_disposable_journal(root, expected_revision=0, phase="fence_requested")
    inspect_disposable_journal(root, require_linux_boot=True)
    with (control / "writer.ready").open("xb") as output:
        output.write(b"PENDING FIXTURE ONLY\n")
    # Keep the original namespace alive so its identifier cannot be recycled
    # while the independent checker is testing another namespace. No release.
    time.sleep(60)


def reject_other_network(control):
    try:
        inspect_disposable_journal(control / "maintenance-journal", require_linux_boot=True)
    except MaintenanceNetworkScopeChanged:
        return {"status": "different_network_namespace_rejected", "read_only": True,
                "production_activation": "disabled", "production_authorized": False,
                "writer_exclusion_verified": False, "restart_inhibition_verified": False,
                "automatic_action": "none"}
    raise RuntimeError("Different network namespace unexpectedly accepted")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", required=True, choices=("prepare", "reject-other-network"))
    args = parser.parse_args()
    control = Path("/control")
    if (control / ".disposable_maintenance_scope").read_bytes() != MARKER:
        raise RuntimeError("Disposable scope marker required")
    if args.role == "prepare":
        prepare(control)
    else:
        print(json.dumps(reject_other_network(control), sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("blocked=" + type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        raise SystemExit(2)
