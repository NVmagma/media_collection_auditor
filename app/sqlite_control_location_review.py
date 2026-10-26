"""Conservative lexical exposure review; never grants control-store authority.

Inputs are detached observations. A clean result cannot prove alias coverage,
permissions, durable storage, or absence of additional writers.
"""
from pathlib import PurePosixPath


class LocationReviewError(ValueError):
    pass


def _path(value):
    if not isinstance(value, str) or not value.startswith('/') or '\\' in value:
        raise LocationReviewError('Expected a canonical absolute POSIX path')
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise LocationReviewError('Control characters in path')
    path = PurePosixPath(value)
    if str(path) != value or '..' in path.parts or value.startswith('//'):
        raise LocationReviewError('Expected a canonical absolute POSIX path')
    return path


def review_control_location(*, candidate_paths, exposures):
    """Review every supplied alias against exports/binds, including read-only ones.

    Each exposure is exactly {kind, path}, with kind nfs_export, smb_share, or
    container_bind. A read-only bind still exposes controller state. Descendant
    exposure roots also conflict: a future control artifact may land there.
    Missing aliases or inventories always remain unresolved, even without overlap.
    """
    if not isinstance(candidate_paths, list) or not candidate_paths:
        raise LocationReviewError('At least one candidate path is required')
    candidates = sorted(set(_path(value) for value in candidate_paths), key=str)
    if not isinstance(exposures, list):
        raise LocationReviewError('Expected exposure observations')
    observed = set()
    for entry in exposures:
        if not isinstance(entry, dict) or set(entry) != {'kind', 'path'}:
            raise LocationReviewError('Invalid exposure observation')
        kind = entry['kind']
        if kind not in ('nfs_export', 'smb_share', 'container_bind'):
            raise LocationReviewError('Unknown exposure kind')
        observed.add((kind, _path(entry['path'])))
    conflicts = []
    for candidate in candidates:
        for kind, exposed in sorted(observed, key=lambda item: (item[0], str(item[1]))):
            if candidate == exposed or exposed in candidate.parents:
                relationship = 'candidate_within_exposure'
            elif candidate in exposed.parents:
                relationship = 'exposure_within_candidate'
            else:
                continue
            conflicts.append({'candidate_path': str(candidate), 'kind': kind,
                              'exposure_path': str(exposed), 'relationship': relationship})
    blockers = ['detached_snapshot_never_establishes_private_storage',
                'alias_and_exposure_coverage_unverified',
                'live_identity_permissions_and_durability_unverified']
    if conflicts:
        blockers.append('observed_exposure_overlap')
    return {'status': 'review_required', 'read_only': True,
            'automatic_action': 'none', 'private_location_verified': False,
            'production_authorized': False, 'production_activation': 'disabled',
            'conflicts': conflicts, 'blockers': blockers}
