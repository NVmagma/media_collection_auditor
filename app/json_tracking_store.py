"""Isolated JSON worker storage; not selected by the production entrypoint.

One existing state file, one shared writer lock, explicit atomic checkpoints.
No release binding, automatic initialization, backend fallback or media actions.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import secrets
import stat

from app.sqlite_json import parse_unique_json
from app.sqlite_lock import audit_run_lock
from app.sqlite_state import validate_snapshot

LIMIT = 32 * 1024 * 1024


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _encode(state):
    validate_snapshot(state)
    raw = (json.dumps(state, sort_keys=True, ensure_ascii=True, allow_nan=False)+'\n').encode()
    if len(raw) > LIMIT: raise RuntimeError('Tracking file exceeds size limit')
    return raw


def _read(parent, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > LIMIT:
            raise RuntimeError('Tracking file unavailable')
        chunks = bytearray()
        while len(chunks) <= LIMIT:
            chunk = os.read(fd, min(65536, LIMIT + 1 - len(chunks)))
            if not chunk: break
            chunks.extend(chunk)
        if len(chunks) > LIMIT or _identity(os.fstat(fd)) != _identity(info):
            raise RuntimeError('Tracking changed during read')
        return bytes(chunks), _identity(info)
    finally: os.close(fd)


class JsonTrackingSession:
    def __init__(self, path, parent, verify_lock):
        self._path, self._parent, self._verify_lock = path, parent, verify_lock
        info = os.fstat(parent)
        self._parent_identity = info.st_dev, info.st_ino
        self._closed = False
        self._raw, self._identity = _read(parent, path.name)
        self.state = parse_unique_json(self._raw)
        _encode(self.state)  # Strict schema and finite values, including extensions.
        self.verify()

    def verify(self):
        if self._closed: raise RuntimeError('Tracking session is closed')
        self._verify_lock()
        current = self._path.parent.stat(follow_symlinks=False)
        if (current.st_dev, current.st_ino) != self._parent_identity:
            raise RuntimeError('Tracking directory changed')
        if _read(self._parent, self._path.name) != (self._raw, self._identity):
            raise RuntimeError('Tracking changed outside the worker')

    def checkpoint(self):
        try:
            self._checkpoint()
        except BaseException:
            # A failure can follow replacement. Prevent callers from continuing
            # an uncertain session or treating a failed intent save as authority.
            self._closed = True
            raise

    def _checkpoint(self):
        raw = _encode(self.state)
        self.verify()
        name = '.json-worker-' + secrets.token_hex(16) + '.tmp'
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=self._parent)
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(raw); handle.flush(); os.fsync(handle.fileno())
            self.verify()
            os.replace(name, self._path.name, src_dir_fd=self._parent, dst_dir_fd=self._parent)
            # Capture the committed file before directory fsync: failures are
            # uncertain, not permission to replay a media/HTTP operation.
            self._raw, self._identity = _read(self._parent, self._path.name)
            if self._raw != raw: raise RuntimeError('Tracking commit changed')
            os.fsync(self._parent)
            self.verify()
        finally:
            try: os.unlink(name, dir_fd=self._parent)
            except FileNotFoundError: pass


class JsonTrackingStore:
    def __init__(self, path):
        self.path = Path(path)
        if (not self.path.is_absolute() or self.path.parent.resolve() != self.path.parent
                or self.path.name in ('', '.', '..')):
            raise ValueError('Canonical absolute tracking path required')

    @contextmanager
    def session(self):
        # Missing state is never interpreted as an empty existing installation.
        parent = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        session = None
        try:
            with audit_run_lock(self.path) as verify_lock:
                session = JsonTrackingSession(self.path, parent, verify_lock)
                yield session
                session.verify()  # No implicit save on exit, including exceptions.
        finally:
            if session is not None: session._closed = True
            os.close(parent)
