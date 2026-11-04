"""Read-only held-path review for configured scheduled lifecycle roots.

No marker requirement and no filesystem mutation or move permit. The caller
supplies stage paths explicitly; neither filesystem names nor pool/share names
are used as an allowlist. Held descriptors do not exclude external writers.
"""
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import os
from pathlib import PurePosixPath
import stat

from app.mount_identity import capture_rename_mount_binding, assert_rename_mount_binding
from app.title_identity import validate_title_folder

STAGES = frozenset(('Waiting', 'Holding', 'Keep', 'Removal'))


def _canonical(value):
    if (not isinstance(value, str) or not value.startswith('/') or value == '/'
            or str(PurePosixPath(value)) != value or '..' in PurePosixPath(value).parts
            or value.startswith('//') or '\\' in value
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError('Canonical absolute stage directories required')
    return value


def _open_directory(path):
    """Resolve every component relative to a no-follow held directory."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK
    fd = os.open('/', flags)
    try:
        for component in PurePosixPath(path).parts[1:]:
            child = os.open(component, flags, dir_fd=fd)
            os.close(fd); fd = child
        return fd
    except BaseException:
        os.close(fd); raise


def _identity(info):
    return info.st_dev, info.st_ino


@dataclass
class HeldScheduledPaths:
    roots: dict
    handles: dict
    source_stage: str
    destination_stage: str
    folder: str
    source_fd: int
    source_identity: tuple
    mount_binding: dict
    process_id: int

    def assert_unchanged(self):
        if os.getpid() != self.process_id:
            raise RuntimeError('Held path process changed')
        for stage, path in self.roots.items():
            fd = _open_directory(path)
            try:
                if _identity(os.fstat(fd)) != _identity(os.fstat(self.handles[stage])):
                    raise RuntimeError('Configured stage identity changed')
            finally:
                os.close(fd)
        for stage, fd in self.handles.items():
            try:
                entry = os.stat(self.folder, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                if stage == self.source_stage:
                    raise RuntimeError('Source entry disappeared') from None
                continue
            if stage != self.source_stage:
                raise RuntimeError('Title destination or alternate stage occupied')
            if not stat.S_ISDIR(entry.st_mode) or _identity(entry) != self.source_identity:
                raise RuntimeError('Source entry replaced')
        assert_rename_mount_binding(self.mount_binding, self.handles[self.source_stage],
                                   self.handles[self.destination_stage], self.source_fd)


@contextmanager
def hold_scheduled_paths(*, stage_roots, source_stage, destination_stage, title_folder):
    validate_title_folder(title_folder)
    if (not isinstance(stage_roots, dict) or set(stage_roots) != STAGES
            or source_stage not in STAGES or destination_stage not in STAGES
            or source_stage == destination_stage):
        raise ValueError('Explicit disjoint lifecycle stage roots required')
    roots = {stage: _canonical(path) for stage, path in stage_roots.items()}
    paths = [PurePosixPath(path) for path in roots.values()]
    if any(a == b or a in b.parents or b in a.parents for i, a in enumerate(paths) for b in paths[i + 1:]):
        raise ValueError('Overlapping stage roots')
    with ExitStack() as stack:
        handles = {}
        for stage, path in roots.items():
            handles[stage] = _open_directory(path)
            stack.callback(os.close, handles[stage])
        if len({_identity(os.fstat(fd)) for fd in handles.values()}) != len(STAGES):
            raise RuntimeError('Aliased stage directories')
        source_fd = os.open(title_folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK,
                            dir_fd=handles[source_stage])
        stack.callback(os.close, source_fd)
        binding = capture_rename_mount_binding(handles[source_stage], handles[destination_stage], source_fd)
        held = HeldScheduledPaths(roots, handles, source_stage, destination_stage, title_folder,
            source_fd, _identity(os.fstat(source_fd)), binding, os.getpid())
        held.assert_unchanged()
        yield held
        held.assert_unchanged()


def review_scheduled_paths(**kwargs):
    base = {'read_only': True, 'authorization': 'not_authorized', 'production_authorized': False,
            'production_activation': 'disabled', 'automatic_action': 'none'}
    try:
        with hold_scheduled_paths(**kwargs):
            return {**base, 'status': 'observed_advisory', 'same_mount_observed': True,
                    'rename_capability': 'requires_disposable_acceptance', 'external_writers_excluded': False}
    except Exception:
        return {**base, 'status': 'blocked', 'reason': 'stage_or_title_binding_unavailable_or_changed'}


@contextmanager
def scan_held_directory(fd):
    """Use an independent directory stream without moving the held FD cursor.

    scandir(fd) duplicates a descriptor, which shares its open-file-description
    position. Opening '.' relative to the held directory gives each verification
    pass its own stream, including filesystem-specific iteration state.
    """
    scan_fd = os.open('.', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK,
                      dir_fd=fd)
    try:
        with os.scandir(scan_fd) as entries:
            yield entries
    finally:
        os.close(scan_fd)
