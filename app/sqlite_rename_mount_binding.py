"""In-process Linux mount binding for held disposable rename descriptors.

These IDs are namespace-local observations, not persisted recovery authority.
"""
import os
from pathlib import Path
import stat


def parse_fd_mount_id(contents):
    if not isinstance(contents, str):
        raise RuntimeError("Descriptor mount information unavailable")
    entries = [line.partition(":")[2].strip() for line in contents.splitlines()
               if line.partition(":")[0] == "mnt_id"]
    if (len(entries) != 1 or not entries[0].isascii()
            or not entries[0].isdecimal() or int(entries[0]) <= 0):
        raise RuntimeError("Descriptor mount ID missing or ambiguous")
    return int(entries[0])


def read_fd_mount_id(fd):
    if type(fd) is not int or fd < 0:
        raise RuntimeError("Valid held descriptor required")
    try:
        return parse_fd_mount_id(Path(f"/proc/self/fdinfo/{fd}").read_text(encoding="ascii"))
    except (OSError, UnicodeError):
        raise RuntimeError("Descriptor mount information unavailable") from None


def read_mount_namespace_identity():
    try:
        info = os.stat("/proc/self/ns/mnt")
    except OSError:
        raise RuntimeError("Mount namespace information unavailable") from None
    return info.st_dev, info.st_ino


def parse_mount_filesystem(contents, mount_id):
    if type(mount_id) is not int or mount_id <= 0 or not isinstance(contents, str):
        raise RuntimeError("Mount filesystem information unavailable")
    matches = []
    for line in contents.splitlines():
        halves = line.split(" - ")
        if len(halves) != 2:
            raise RuntimeError("Malformed mount filesystem information")
        fields, filesystem = halves[0].split(), halves[1].split()
        if (len(fields) < 6 or len(filesystem) < 3 or not fields[0].isascii()
                or not fields[0].isdecimal()):
            raise RuntimeError("Malformed mount filesystem information")
        if int(fields[0]) == mount_id:
            matches.append(filesystem[0])
    if len(matches) != 1:
        raise RuntimeError("Mount filesystem missing or ambiguous")
    return matches[0]


def read_mount_filesystem(mount_id):
    try:
        contents = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise RuntimeError("Mount filesystem information unavailable") from None
    return parse_mount_filesystem(contents, mount_id)


def capture_rename_mount_binding(source_parent_fd, destination_parent_fd, witness_fd):
    """Require all three held directories on one mount and one device."""
    try:
        namespace_device, namespace_inode = read_mount_namespace_identity()
        entries = []
        for fd in (source_parent_fd, destination_parent_fd, witness_fd):
            info = os.fstat(fd)
            if not stat.S_ISDIR(info.st_mode):
                raise RuntimeError("Rename witness must be a directory")
            entries.append({"mount_id": read_fd_mount_id(fd), "device": info.st_dev,
                            "inode": info.st_ino})
    except OSError:
        raise RuntimeError("Rename mount binding unavailable") from None
    if len({entry["mount_id"] for entry in entries}) != 1 or len({entry["device"] for entry in entries}) != 1:
        raise RuntimeError("Rename requires one observed mount and device")
    filesystem = read_mount_filesystem(entries[0]["mount_id"])
    if filesystem == "fuse.shfs":
        raise RuntimeError("fuse.shfs blocked: required no-replace rename unsupported on verified deployment")
    return {"filesystem": filesystem,
            "namespace_device": namespace_device, "namespace_inode": namespace_inode,
            "directories": entries}


def assert_rename_mount_binding(expected, source_parent_fd, destination_parent_fd, witness_fd):
    if capture_rename_mount_binding(source_parent_fd, destination_parent_fd, witness_fd) != expected:
        raise RuntimeError("Rename mount binding changed")
