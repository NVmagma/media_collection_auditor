from copy import deepcopy
import json
import pytest
from scripts.unraid_update_plan import proposed_update


def inputs():
    return dict(container={'Name': '/media_collection_auditor', 'Image': 'sha256:' + 'a' * 64},
        image={'Id': 'sha256:' + 'b' * 64, 'Config': {'Entrypoint': ['python', '-m', 'app.main'],
            'Cmd': None, 'StopSignal': 'SIGINT', 'Volumes': None, 'Labels': {
                'org.opencontainers.image.revision': 'c' * 40,
                'io.media-collection-auditor.sqlite-activation': 'preview-only'}}},
        packaged_profile='scheduled-preview-v1', packaged_revision='c' * 40,
        binding_revision='c' * 40, binding_validation='valid')


def test_full_validation_required_even_when_revision_matches():
    data = inputs()
    result = proposed_update(**data)
    assert result['status'] == 'candidate_matches_existing_binding'
    assert result['candidate_binding_verified'] is True and result['update_authorized'] is False
    data['binding_validation'] = 'invalid'
    assert proposed_update(**data)['candidate_binding_verified'] is False


def test_new_image_source_never_reuses_existing_binding():
    data = inputs(); data['binding_revision'] = 'd' * 40
    result = proposed_update(**data)
    assert result['requires_fresh_preparation'] is True
    assert 'candidate_source_requires_new_binding' in result['blockers']
    assert result['candidate_binding_verified'] is False


@pytest.mark.parametrize('field,value', [('Entrypoint', ['sh']), ('Cmd', ['private-secret']),
    ('StopSignal', 'SIGTERM'), ('Volumes', {'/private-secret': {}})])
def test_changed_entrypoint_command_signal_or_volumes_block(field, value):
    data = inputs(); data['image']['Config'][field] = value
    result = proposed_update(**data)
    assert 'candidate_runtime_contract_changed' in result['blockers']
    assert 'private-secret' not in json.dumps(result)


def test_forged_labels_sealed_profile_and_changing_binding_block():
    for change in ('labels', 'profile', 'binding'):
        data = inputs()
        if change == 'labels': data['image']['Config']['Labels']['org.opencontainers.image.revision'] = 'f' * 40
        if change == 'profile': data['packaged_profile'] = 'sealed'
        if change == 'binding': data['binding_validation'] = 'changed'
        assert proposed_update(**data)['candidate_binding_verified'] is False


def test_missing_inputs_never_echo_private_payload():
    data = inputs(); data['container'] = {'private-secret': 'private-secret'}
    result = proposed_update(**data)
    assert result['status'] == 'review_required' and result['update_authorized'] is False
    assert 'private-secret' not in json.dumps(result)
