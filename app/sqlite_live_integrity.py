"""Opt-in mutable-state integrity for the future live binding, not activation.

A state digest is committed in the same SQLite transaction as each guarded
revision. It detects inconsistent/raw state changes, not malicious privileged
rewrites of both metadata and state. Existing preview/legacy databases opt out.
"""
import hashlib
import json
from app.sqlite_json import parse_unique_json

KEY='live_state_integrity_v1'


def record(state,revision):
    if type(revision) is not int or revision<0:raise RuntimeError('Invalid live state revision')
    raw=json.dumps(state,ensure_ascii=True,allow_nan=False,sort_keys=True,separators=(',',':')).encode('ascii')
    return json.dumps({'revision':revision,'sha256':hashlib.sha256(raw).hexdigest()},sort_keys=True,separators=(',',':'))


def verify(raw,state,revision):
    try:
        value=parse_unique_json(raw.encode('utf-8'))
        expected=parse_unique_json(record(state,revision).encode('ascii'))
        if (not isinstance(value,dict) or set(value)!={'revision','sha256'}
                or type(value['revision']) is not int or value!=expected):
            raise RuntimeError('Live state integrity mismatch')
    except (ValueError,TypeError,AttributeError,UnicodeError):
        raise RuntimeError('Live state integrity unavailable') from None


def initialize(connection,*,state,revision):
    """Called only by an explicit offline binder inside its existing transaction.

    Never creates a database/schema, overwrites an existing record or advances
    tracking. The caller must have verified/pinned the source and SQLite state.
    """
    if not connection.in_transaction:raise RuntimeError('Explicit offline transaction required')
    connection.execute('INSERT INTO metadata(key,value) VALUES (?,?)',(KEY,record(state,revision)))
