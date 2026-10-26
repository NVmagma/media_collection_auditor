"""Three-domain admission wrapper for marked disposable copy only.

No host installer, service controls, backend fallback or production authority.
"""
from app.sqlite_disposable_boundary_set import compose_disposable_boundaries
from app.sqlite_maintenance_bound_copy import run_maintenance_bound_disposable_copy


def run_unified_disposable_copy(*, docker, nfs, host_storage, **arguments):
    if '_fixture_boundary_observer' in arguments:
        raise ValueError('Unified disposable domain checks cannot be overridden')
    observer = compose_disposable_boundaries(docker=docker, nfs=nfs, host_storage=host_storage)
    result = run_maintenance_bound_disposable_copy(**arguments, _fixture_boundary_observer=observer)
    return {**result, 'boundary_mode': 'disposable_required_domains',
            'external_writer_exclusion_verified': False, 'production_authorized': False,
            'release_authorized': False}
