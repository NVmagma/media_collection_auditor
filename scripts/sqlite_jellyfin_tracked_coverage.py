#!/usr/bin/env python3
"""GET-only tracked-title probe against an existing read-only lab database."""
import argparse
import json
import os
import sys
from urllib.parse import urlparse

import requests

from app.sqlite_jellyfin_coverage_probe import probe_coverage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    args = parser.parse_args()
    url = os.environ.get("JELLYFIN_HOST_URL", "").rstrip("/")
    token = os.environ.get("JELLYFIN_API_TOKEN", "").strip()
    parsed = urlparse(url)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or
            parsed.username or parsed.password or parsed.query or parsed.fragment or not token):
        print("Valid Jellyfin host and token required in environment.", file=sys.stderr)
        return 2
    try:
        with requests.Session() as session:
            session.trust_env = False
            session.headers.update({"Authorization": (
                "MediaBrowser Client=MediaCollectionAuditor, Device=Unraid, "
                "DeviceId=sqlite-coverage-readonly, Version=1.0, Token=" + token)})

            def fetch(path, params):
                response = session.get(url + path, params=params, timeout=20,
                                       allow_redirects=False)
                if 300 <= response.status_code < 400:
                    raise ValueError("Redirect rejected")
                response.raise_for_status()
                return response.json()

            report = probe_coverage(args.database, fetch)
    except Exception:
        # Never echo transport exceptions, credentials, database paths or titles.
        print(json.dumps({"status": "blocked", "coverage_complete": False,
                          "failure_category": "probe_unavailable", "read_only": True,
                          "production_authorized": False}))
        return 1
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0 if report["coverage_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
