"""Reject unsupported storage selections before any worker side effects."""
def require_json_backend(value):
    if value != 'json':
        raise RuntimeError('AUDITOR_STATE_BACKEND must be json')
