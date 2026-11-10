#!/usr/bin/env python3
"""Print tracking status without private details, service requests, or service controls."""
import argparse
import json

from app.integration_status import read_tracking_status


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True)
    args = parser.parse_args(argv)
    report = read_tracking_status(args.state)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 2 if report["status"] == "unavailable" else 0


if __name__ == "__main__":
    raise SystemExit(main())
