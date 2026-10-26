"""Redacted proposed-image review. A matching report never authorizes an update."""
import re

REVISION = re.compile(r'[0-9a-f]{40}')
IMAGE = re.compile(r'sha256:[0-9a-f]{64}')


def proposed_update(*, container, image, packaged_profile, packaged_revision,
                    binding_revision, binding_validation):
    report = {'status': 'review_required', 'read_only': True, 'automatic_action': 'none',
              'update_authorized': False, 'media_actions_authorized': False,
              'candidate_binding_verified': False}
    blockers = []
    try:
        if container.get('Name') != '/media_collection_auditor' or not IMAGE.fullmatch(container['Image']):
            raise ValueError('invalid_container')
        if not IMAGE.fullmatch(image['Id']):
            raise ValueError('invalid_image')
        config = image['Config']
        labels = config.get('Labels') or {}
        if (packaged_profile != 'scheduled-preview-v1'
                or not isinstance(packaged_revision, str) or not REVISION.fullmatch(packaged_revision)
                or labels.get('org.opencontainers.image.revision') != packaged_revision
                or labels.get('io.media-collection-auditor.sqlite-activation') != 'preview-only'):
            blockers.append('candidate_preview_profile_unverified')
        if (config.get('Entrypoint') != ['python', '-m', 'app.main']
                or config.get('Cmd') not in (None, []) or config.get('StopSignal') != 'SIGINT'
                or config.get('Volumes') not in (None, {})):
            blockers.append('candidate_runtime_contract_changed')
        if not isinstance(binding_revision, str) or not REVISION.fullmatch(binding_revision):
            blockers.append('existing_binding_revision_unavailable')
        elif binding_revision != packaged_revision:
            blockers.append('candidate_source_requires_new_binding')
            report['requires_fresh_preparation'] = True
        if binding_validation == 'changed':
            blockers.append('binding_changed_during_review')
        elif binding_validation != 'valid':
            blockers.append('candidate_binding_validation_failed')
        if not blockers:
            report['status'] = 'candidate_matches_existing_binding'
            report['candidate_binding_verified'] = True
            report['requires_fresh_preparation'] = False
        report['image_change_observed'] = image['Id'] != container['Image']
    except (KeyError, TypeError, ValueError, AttributeError):
        blockers.append('candidate_inventory_unreadable_or_unsupported')
    report['blockers'] = sorted(set(blockers))
    return report
