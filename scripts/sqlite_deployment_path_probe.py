#!/usr/bin/env python3
"""Read-only deployment metadata. Run via docker exec python - < this file.

Standard library only. Does not import/run the auditor, list titles, write files,
read state databases, call services, or print credential/environment dumps.
"""
import json
import os
from pathlib import Path


DEFAULTS = {"RADARR": {"transient": "Movies", "holding": "Movies_hold",
                       "keep": "Movies_keep", "removal": "Movies_removal"},
            "SONARR": {"transient": "TV", "holding": "TV_hold",
                       "keep": "TV_keep", "removal": "TV_removal"}}


def inspect_directory(path):
    if (not isinstance(path, str) or not path.startswith("/")
            or os.path.normpath(path) != path or chr(92) in path
            or any(ord(char) < 32 for char in path)):
        return {"status": "invalid_path"}
    # Refuse aliases rather than declaring them equal from path text alone.
    if os.path.realpath(path) != path:
        return {"path": path, "status": "symlink_or_path_alias"}
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        return {"path": path, "status": "unavailable_or_not_directory"}
    try:
        info = os.fstat(fd)
        mount_id = None
        try:
            lines = Path(f"/proc/self/fdinfo/{fd}").read_text(encoding="ascii").splitlines()
            values = [line.partition(":")[2].strip() for line in lines
                      if line.partition(":")[0] == "mnt_id"]
            if len(values) == 1 and values[0].isascii() and values[0].isdecimal() and int(values[0]) > 0:
                mount_id = int(values[0])
        except (OSError, UnicodeError):
            pass
        return {"path": path, "status": "observed", "device": info.st_dev,
                "inode": info.st_ino, "mount_id": mount_id}
    finally:
        os.close(fd)


def probe_paths(environment, web_config, inspect=inspect_directory):
    """Candidate paths reflect known defaults/overrides, not runtime authority."""
    base = environment.get("MEDIA_PATH", "/media")
    if isinstance(web_config, dict) and isinstance(web_config.get("MEDIA_PATH"), str):
        base = web_config["MEDIA_PATH"]
    if not isinstance(base, str) or not base.startswith("/") or os.path.normpath(base) != base:
        return {"status": "blocked", "reason": "invalid_media_base",
                "read_only": True, "production_authorized": False}
    libraries = {}
    for prefix, defaults in DEFAULTS.items():
        stages = {}
        remote = {}
        for stage, folder in defaults.items():
            override = (environment.get(f"{prefix}_{stage.upper()}_PATH") or "").strip()
            candidate = override or os.path.join(base, folder)
            stages[stage] = inspect(candidate)
            if stage != "transient":
                app_path = (environment.get(f"{prefix}_APP_{stage.upper()}_PATH") or "").strip() or candidate
                remote[stage] = {"path": app_path} if app_path.startswith("/") else {"status": "invalid_path"}
        rows = list(stages.values())
        mounts = {row.get("mount_id") for row in rows}
        same = (len(mounts) == 1) if all(row.get("status") == "observed" and row.get("mount_id") is not None
                                       for row in rows) else None
        libraries[prefix.lower()] = {"candidate_stage_paths": stages,
                                     "declared_arr_paths_unverified": remote,
                                     "same_observed_mount": same}
    return {"status": "review_required", "read_only": True,
            "production_authorized": False, "configuration_verified": False,
            "writer_exclusion_verified": False, "libraries": libraries}


def main():
    config = {}
    config_status = "unavailable"
    try:
        config_path = Path(os.environ.get("WEB_CONFIG_FILE", "/app/logs/auditor_config.json"))
        parsed = json.loads(config_path.read_text())
        if isinstance(parsed, dict):
            config = {"MEDIA_PATH": parsed["MEDIA_PATH"]} if "MEDIA_PATH" in parsed else {}
            config_status = "read"
        else:
            config_status = "invalid_shape"
    except (OSError, ValueError, UnicodeError):
        pass
    report = probe_paths(os.environ, config)
    report["web_config_status"] = config_status
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
