"""Safe deployment metadata: no auditor import, mutation, or secret output."""
import json

from scripts.sqlite_deployment_path_probe import inspect_directory, probe_paths


def observed(path):
    return {"path": path, "status": "observed", "mount_id": 7}


def test_path_allowlist_never_emits_connection_secrets():
    report = probe_paths({"MEDIA_PATH": "/media", "RADARR_API_KEY": "private-token",
                          "JELLYFIN_HOST_URL": "http://private-server"},
                         {"SONARR_API_KEY": "another-secret"}, inspect=observed)
    output = json.dumps(report)
    assert all(value not in output for value in ["private-token", "private-server", "another-secret"])
    assert report["production_authorized"] is False
    assert report["writer_exclusion_verified"] is False
    assert report["configuration_verified"] is False


def test_web_base_and_environment_specific_overrides_are_kept_separate():
    report = probe_paths({"MEDIA_PATH": "/fallback", "RADARR_KEEP_PATH": "/specific/keep",
                          "RADARR_APP_KEEP_PATH": "/arr/keep"},
                         {"MEDIA_PATH": "/web"}, inspect=observed)
    movie = report["libraries"]["radarr"]
    assert movie["candidate_stage_paths"]["transient"]["path"] == "/web/Movies"
    assert movie["candidate_stage_paths"]["keep"]["path"] == "/specific/keep"
    assert movie["declared_arr_paths_unverified"]["keep"]["path"] == "/arr/keep"


def test_missing_mount_information_is_unknown_not_equal():
    report = probe_paths({}, {}, inspect=lambda path: {"path": path, "status": "unavailable"})
    assert report["libraries"]["radarr"]["same_observed_mount"] is None


def test_distinct_mounts_are_reported_without_authorization():
    def inspect(path):
        return {"path": path, "status": "observed", "mount_id": 8 if path.endswith("_keep") else 7}
    report = probe_paths({}, {}, inspect=inspect)
    assert report["libraries"]["radarr"]["same_observed_mount"] is False
    assert report["production_authorized"] is False


def test_real_directory_inspection_is_read_only(tmp_path):
    (tmp_path / "preserve").write_text("unchanged")
    before = sorted(path.name for path in tmp_path.iterdir())
    result = inspect_directory(str(tmp_path.resolve()))
    assert result["status"] == "observed"
    assert sorted(path.name for path in tmp_path.iterdir()) == before
    assert (tmp_path / "preserve").read_text() == "unchanged"


def test_symlink_and_relative_paths_are_not_observed(tmp_path):
    alias = tmp_path / "alias"
    target = tmp_path / "target"
    target.mkdir()
    alias.symlink_to(target)
    assert inspect_directory(str(alias))["status"] != "observed"
    assert inspect_directory("relative")["status"] == "invalid_path"
