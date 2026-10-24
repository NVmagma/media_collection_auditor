"""Read retained disposable dispatch evidence; never restore services."""
import argparse
import json

from app.sqlite_disposable_dispatch_recovery import review_disposable_controller_recovery


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True)
    args=parser.parse_args()
    print(json.dumps(review_disposable_controller_recovery(args.root),indent=2,sort_keys=True))


if __name__=='__main__':
    main()
