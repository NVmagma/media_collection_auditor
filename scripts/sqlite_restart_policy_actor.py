"""Fixed disposable actor; never accepts commands, network targets or media paths."""
import os
from pathlib import Path
import signal
import time

MARKER = b"DISPOSABLE RESTART POLICY FIXTURE\n"


def start(root):
    if (root / ".fixture-only").read_bytes() != MARKER:
        raise RuntimeError("Not a disposable restart fixture")
    count = int((root / "starts").read_text()) + 1
    if count > 3:
        raise RuntimeError("Fixture restart bound exceeded")
    (root / "starts").write_text(str(count))
    return count


def crash_requested(root, count):
    # Each process observes its own fixed request, so a restart cannot replay it.
    return (root / ("crash." + str(count))).exists()


def main():
    root = Path("/fixture")
    signal.alarm(90)  # on-failure:2 also bounds orphan restarts
    count = start(root)
    while True:
        if crash_requested(root, count):
            os._exit(17)
        time.sleep(0.1)


if __name__ == "__main__":
    main()
