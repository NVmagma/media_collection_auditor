"""Create a NEW synthetic NFS config lab; never read or write host settings."""
import argparse
import json
from pathlib import Path
from app.sqlite_disposable_nfs_config_plan import MARKER, prepare_disposable_nfs_config_plan


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True)
    args=parser.parse_args()
    root=Path(args.root)
    if not root.is_absolute() or root.resolve()!=root:
        raise ValueError('New canonical disposable root required')
    root.mkdir(mode=0o700)
    (root/'.disposable_host_config').write_bytes(MARKER)
    (root/'share.cfg').write_bytes(b'# SYNTHETIC CONFIG ONLY\nshareNFSEnabled="yes"\nfixtureOther="preserved"\n')
    print(json.dumps(prepare_disposable_nfs_config_plan(root),sort_keys=True))


if __name__=='__main__':main()
