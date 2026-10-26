"""Prepare a new synthetic private packet for the real read-only host launcher."""
from pathlib import Path

from app.sqlite_preview_cutover import write_review_packet
from scripts.sqlite_preview_cutover_fixture import PreviewCutoverFixtureTests, OLD, CONTROL
from scripts.sqlite_preview_release_request import fingerprint


def prepare(directory, image_id, worker_revision):
    case = PreviewCutoverFixtureTests(); case.setUp()
    try:
        case.root = Path(directory)
        case.old[0]['HostConfig']['PortBindings'] = {'8080/tcp': [{'HostIp': '', 'HostPort': '8089'}]}
        case.inputs()
        (case.root / 'original-template.xml').write_text('<Container><Name>media_collection_auditor</Name></Container>')
        report = write_review_packet(directory=case.root, preview_image=image_id, rollback_image=OLD,
            control_host=CONTROL, source_revision=worker_revision)
        return fingerprint(report)
    finally:
        case.doCleanups()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--packet-directory', required=True)
    parser.add_argument('--image-id', required=True)
    parser.add_argument('--worker-revision', required=True)
    args = parser.parse_args()
    print(prepare(args.packet_directory, args.image_id, args.worker_revision))
