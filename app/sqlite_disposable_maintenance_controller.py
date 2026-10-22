"""Exercise intent/action/outcome ordering with fixed synthetic receipts ONLY.

Receipts are not fences: this module has no external enforcement backend,
service access, media operations or arbitrary command/callback API.
"""
import os
import stat

from app.sqlite_disposable_maintenance_journal import _append, _database, _root

RECEIPT = b"SYNTHETIC ACTION ONLY; NO WRITERS EXCLUDED\n"


def _receipt_identity(info):
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise RuntimeError("Unsafe synthetic receipt")
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _receipt(root, action):
    # Exclusive, retained receipt stands in for an external action in this lab.
    # Never overwrite it or infer that its existence authorizes replay/recovery.
    with (root / (action + ".fixture-receipt")).open("xb") as output:
        output.write(RECEIPT)
        output.flush()
        os.fsync(output.fileno())
        identity = _receipt_identity(os.fstat(output.fileno()))
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return identity


def _verify_receipt(root, action, identity):
    path = root / (action + ".fixture-receipt")
    if _receipt_identity(path.lstat()) != identity:
        raise RuntimeError("Synthetic receipt identity changed")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if (_receipt_identity(os.fstat(fd)) != identity
                or os.read(fd, len(RECEIPT) + 1) != RECEIPT
                or _receipt_identity(os.fstat(fd)) != identity
                or _receipt_identity(path.lstat()) != identity):
            raise RuntimeError("Synthetic receipt verification failed")
    finally:
        os.close(fd)


def _run(root, *, expected_revision, requested, completed, action):
    root = _root(root)
    # One nonblocking controller lock spans durable intent, synthetic action,
    # and outcome. Committing intent does not release this process lock.
    with _database(root, with_verifier=True) as (db, verify):
        _append(db, expected_revision=expected_revision, phase=requested)
        db.commit()  # MUST precede the action; failure leaves no action attempt.
        verify()
        receipt = _receipt(root, action)
        verify()
        _verify_receipt(root, action, receipt)
        db.execute("BEGIN IMMEDIATE")
        report = _append(db, expected_revision=expected_revision + 1, phase=completed)
        _verify_receipt(root, action, receipt)
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
