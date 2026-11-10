"""Reject unsupported storage settings before the worker changes anything."""
def require_json_backend(value):
    if value != 'json':
        raise RuntimeError('AUDITOR_STATE_BACKEND must be json')
