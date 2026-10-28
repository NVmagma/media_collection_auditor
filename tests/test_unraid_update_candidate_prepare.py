"""Cross-version candidate preparation cannot become a service transaction."""
import json
import pytest
import sys

pytestmark=pytest.mark.skipif(sys.platform!='linux',reason='Linux private preview preparation')
from scripts import unraid_update_prepare_fixture as preparation_fixture
identity=preparation_fixture.identity
from scripts.unraid_update_candidate_prepare import prepare_candidate


@pytest.fixture
def candidate_case():
    case=preparation_fixture.ReplacementPrepareTests();case.setUp()
    try:yield case
    finally:case.doCleanups()


def prepare(case,**changes):
    args=dict(image=case.image,expected_image_id=case.image['Id'],backup=case.backup,
        backup_identity=identity(case.backup),fingerprint=case.fingerprint,logs=case.logs,
        logs_identity=identity(case.logs),control=case.control,control_identity=identity(case.control))
    args.update(changes);return prepare_candidate(**args)


def test_different_image_preserves_state_and_never_builds_service_payload(candidate_case):
    case=candidate_case
    result=prepare(case)
    assert result['status']=='candidate_files_prepared_not_started'
    assert result['source_revision']=='b'*40 and result['tracking_preserved'] and result['settings_preserved']
    assert not result['container_payload_prepared'] and not result['deployment_authorized']
    assert not result['registry_reference_configured'] and not result['backup_freshness_verified']
    assert not (case.logs/'create-payload.json').exists()
    assert 'fixture-private-secret' not in json.dumps(result)
    case.unchanged()


def test_wrong_selected_image_refuses_before_files(candidate_case):
    case=candidate_case
    with pytest.raises(ValueError):prepare(case,expected_image_id='sha256:'+'f'*64)
    assert not list(case.logs.iterdir()) and not list(case.control.iterdir())


def test_success_is_not_replayable(candidate_case):
    case=candidate_case
    prepare(case)
    before={path:path.read_bytes() for root in (case.logs,case.control) for path in root.rglob('*') if path.is_file()}
    with pytest.raises(RuntimeError):prepare(case)
    assert before=={path:path.read_bytes() for path in before}
    case.unchanged()
