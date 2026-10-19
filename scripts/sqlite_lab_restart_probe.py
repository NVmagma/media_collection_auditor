"""Test-only container restart persistence probe; never accesses media or services.

Run 'create' in one ephemeral lab container and 'verify' in a newly created
container using the same isolated /lab bind mount. No cleanup is automatic.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

LAB = Path("/lab")
MARKER = LAB / "sqlite_restart_probe.json"
PAYLOAD = {"schema": 1, "purpose": "isolated-container-restart", "state": "pending"}


def probe(action: str) -> None:
    if LAB.is_symlink() or not LAB.is_dir():
        raise RuntimeError("Missing or symlinked lab mount")
    if action == "create":
        # Exclusive creation prevents accidentally resetting a previous result.
        with MARKER.open("x", encoding="utf-8") as handle:
            json.dump(PAYLOAD, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            import os
            os.fsync(handle.fileno())
        print("Created disposable restart marker")
    elif action == "verify":
        if MARKER.is_symlink():
            raise RuntimeError("Refusing symlinked marker")
        content = MARKER.read_bytes()
        if json.loads(content) != PAYLOAD:
            raise RuntimeError("Restart marker contents differ")
        print("Restart marker verified, sha256=" + hashlib.sha256(content).hexdigest())
    else:
        raise RuntimeError("Expected create or verify")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m scripts.sqlite_lab_restart_probe create|verify")
    try:
        probe(sys.argv[1])
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"Lab restart probe blocked: {exc}") from exc
