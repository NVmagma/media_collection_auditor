"""Read-only report; no media path access, intent clearance or replay."""
import argparse
import json
from app.sqlite_scheduled_pending_review import review_scheduled_pending


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    report = review_scheduled_pending(parser.parse_args().database)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 2 if report['status'] == 'blocked' else 0


if __name__ == '__main__':
    raise SystemExit(main())
