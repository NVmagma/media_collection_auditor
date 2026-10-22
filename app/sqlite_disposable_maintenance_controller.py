"""Exercise intent/action/outcome ordering with fixed synthetic receipts ONLY.

Receipts are not fences: this module has no external enforcement backend,
service access, media operations or arbitrary command/callback API.
"""
import os

from app.sqlite_disposable_maintenance_journal import _append, _database, _root


def _receipt(root, action):
    # Exclusive, retained receipt stands in for an external action in this lab.
    # Never overwrite it or infer that its existence authorizes replay/recovery.
    with (root / (action + ".fixture-receipt")).open("xb") as output:
        output.write(b"SYNTHETIC ACTION ONLY; NO WRITERS EXCLUDED\n")
        output.flush()
        os.fsync(output.fileno())
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _run(root, *, expected_revision, requested, completed, action):
    root = _root(root)
    # One nonblocking controller lock spans durable intent, synthetic action,
    # and outcome. Committing intent does not release this process lock.
    with _database(root, with_verifier=True) as (db, verify):
        _append(db, expected_revision=expected_revision, phase=requested)
        db.commit()  # MUST precede the action; failure leaves no action attempt.
        verify()
        _receipt(root, action)
        verify()
        db.execute("BEGIN IMMEDIATE")
        report = _append(db, expected_revision=expected_revision + 1, phase=completed)
    return report


def fence_disposable_fixture(root, *, expected_revision):
    """Record intent, create a synthetic receipt, record observed completion.

    A pending request is deliberately NOT retryable through this API.
    """
    return _run(root, expected_revision=expected_revision, requested="fence_requested",
                completed="fixture_fenced", action="fence")


def release_disposable_fixture(root, *, expected_revision):
    """Require explicit verified outcomes before a synthetic release attempt."""
    return _run(root, expected_revision=expected_revision, requested="release_requested",
                completed="released", action="release")
