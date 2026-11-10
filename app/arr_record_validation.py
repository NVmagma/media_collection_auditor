"""Check fresh Radarr or Sonarr records before accepting an update result.

The caller must fetch the data from the correct service with authentication.
Nothing here contacts or changes Arr. A matching record alone is not enough to
clear a pending operation.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any


def inspect_arr_sync(details: dict[str, Any], record: dict[str, Any] | None) -> str:
    """Compare one Arr record with the pending update.

    Require the exact integer ID, a normalized absolute POSIX path, and a real
    boolean monitoring value. Do not guess from the title text.
    """
    validate_arr_sync_details(details)
    title_id, root, monitored = details["title_id"], details["root"], details["monitored"]
    if not isinstance(record, dict):
        raise RuntimeError("Arr response unavailable; refusing to infer success")
    if type(record.get("id")) is not int or record["id"] != title_id:
        raise RuntimeError("Arr title identity mismatch")
    if type(record.get("monitored")) is not bool:
        raise RuntimeError("Arr monitoring status unavailable")
    path = record.get("path")
    if not isinstance(path, str) or not path.startswith("/"):
        raise RuntimeError("Arr title path unavailable")
    record_path = PurePosixPath(path)
    if (".." in record_path.parts or str(record_path) != path
            or record_path == PurePosixPath("/")):
        raise RuntimeError("Arr title path invalid")
    if record_path.parent != PurePosixPath(root):
        return "root_mismatch"
    if record["monitored"] != monitored:
        return "monitoring_mismatch"
    return "matching_record_unverified"



def validate_arr_sync_details(details):
    """Validate request shape only; this is not remote outcome verification."""
    if not isinstance(details, dict):
        raise RuntimeError("Arr intent details are invalid")
    service = details.get("service")
    title_id = details.get("title_id")
    root = details.get("root")
    monitored = details.get("monitored")
    if service not in ("radarr", "sonarr"):
        raise RuntimeError("Arr service must be radarr or sonarr")
    if type(title_id) is not int or title_id <= 0:
        raise RuntimeError("Arr title ID must be a positive integer")
    if type(monitored) is not bool:
        raise RuntimeError("Arr monitoring status must be a boolean")
    if (not isinstance(root, str) or not root.startswith("/")
            or ".." in PurePosixPath(root).parts
            or str(PurePosixPath(root)) != root):
        raise RuntimeError("Arr root path is invalid")
