"""Prepare review artifacts from a marked disposable share.cfg; never apply."""
import argparse
import json

from app.sqlite_boot_share_config_candidate import prepare_disposable_boot_share_config_plan


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True)
    print(json.dumps(prepare_disposable_boot_share_config_plan(parser.parse_args().root),
                     indent=2,sort_keys=True))
