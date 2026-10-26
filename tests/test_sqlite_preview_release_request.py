import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from app import sqlite_release_profile as build
from app.sqlite_preview_activation import PROFILE
from scripts import sqlite_preview_cutover_fixture as packet_fixture
from scripts.sqlite_preview_cutover_fixture import NEW, REVISION, IDENTIFIER
from scripts.sqlite_preview_release_request import fingerprint, verify, REPOSITORY


@pytest.fixture
def request_case():
    case = packet_fixture.PreviewCutoverFixtureTests(); case.setUp()
    case.old[0]['HostConfig']['PortBindings'] = {'8080/tcp': [{'HostIp': '', 'HostPort': '8089'}]}
    case.inputs()
    (case.root / 'original-template.xml').write_text('<Container><Name>media_collection_auditor</Name></Container>')
    report = case.write()
    info = case.root.stat()
    with patch.object(build, 'PROFILE', PROFILE), patch.object(build, 'SOURCE_REVISION', REVISION):
        try: yield case, report, (info.st_dev, info.st_ino)
        finally: case.doCleanups()


def call(case, report, identity, action='review', **changes):
    return verify(directory=case.root, expected_identity=identity, image_id=NEW,
        expected_fingerprint=changes.get('fingerprint', fingerprint(report)), action=action)


def test_public_selection_verifies_exact_private_inputs_without_service_actions(request_case):
    case, report, identity = request_case
    before = {p.name: p.read_bytes() for p in case.root.iterdir()}
    result = call(case, report, identity)
    assert result['status'] == 'production_release_selection_verified_not_executed'
    assert result['original_container_id'] == IDENTIFIER
    assert result['registry_tag'].startswith(REPOSITORY + ':sqlite-preview-')
    assert result['service_actions_performed'] is False
    assert result['registry_publication_performed'] is False
    assert {p.name: p.read_bytes() for p in case.root.iterdir()} == before
    assert call(case, report, identity, 'review-sha') == hashlib.sha256(before['review.json']).hexdigest()
    assert call(case, report, identity, 'control-path') == report['control_host_path']


def test_wrong_public_selection_never_rewrites_private_packet(request_case):
    case, report, identity = request_case
    with pytest.raises(RuntimeError, match='differs from approved fingerprint'):
        call(case, report, identity, fingerprint='0' * 64)
    assert not (case.root / 'service-request.json').exists()


def test_any_selected_image_input_template_or_policy_change_changes_fingerprint(request_case):
    from copy import deepcopy
    _, report, _ = request_case
    for field in ('preview_image_id', 'original_container_id', 'proposed_template_sha256',
                  'worker_revision', 'control_host_path', 'daily_time'):
        altered = deepcopy(report)
        key = 'source_revision' if field == 'worker_revision' else field
        value = altered[key]
        altered[key] = (('sha256:' + 'e' * 64) if key.endswith('image_id') else
                        'e' * 64 if key.endswith(('_id', '_sha256')) else
                        'e' * 40 if key == 'source_revision' else value + '-changed')
        assert fingerprint(altered) != fingerprint(report)
    altered = deepcopy(report); altered['input_sha256']['original-config.json'] = 'f' * 64
    assert fingerprint(altered) != fingerprint(report)


def test_registry_reference_requires_retained_matching_service_request(request_case):
    import json
    case, report, identity = request_case
    reference = REPOSITORY + '@sha256:' + 'e' * 64
    request = {'reference': reference, 'preview_image_id': NEW,
        'context': {'approved_review_sha256': call(case, report, identity, 'review-sha')}}
    (case.root / 'service-request.json').write_text(json.dumps(request))
    assert call(case, report, identity, 'reference') == reference
    request['preview_image_id'] = 'sha256:' + 'f' * 64
    (case.root / 'service-request.json').write_text(json.dumps(request))
    with pytest.raises(RuntimeError, match='differs from approved selection'):
        call(case, report, identity, 'reference')
