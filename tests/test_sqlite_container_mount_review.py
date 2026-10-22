import io
import json

import pytest

from app.sqlite_container_mount_review import review_container_mounts
from scripts.sqlite_container_mount_review import main

ROOTS = ["/mnt/user/media", "/mnt/pool/media"]


def mount(source, destination, rw=True, kind="bind"):
    return {"Source": source, "Destination": destination, "RW": rw, "Type": kind}


def record(*mounts, **changes):
    result = {"kind": "container", "name": "/fixture", "running": True, "paused": False,
              "restart": "no", "privileged": False, "pid_mode": "", "cap_add": None,
              "device_count": 0, "mounts": list(mounts)}
    result.update(changes)
    return result


def review(*records):
    return review_container_mounts(list(records), media_roots=ROOTS)


@pytest.mark.parametrize("source", ["/mnt/user/media/Movies", "/mnt/pool/media/TV", "/mnt", "/"])
def test_parent_child_and_declared_alias_sources_are_reviewed_even_when_stopped(source):
    report = review(record(mount(source, "/media"), running=False, restart="always"))
    item = report["containers_requiring_review"][0]
    assert "writable_declared_media_mount" in item["issues"]
    assert item["running"] is False
    assert item["restart"] == "always"
    assert report["writer_exclusion_verified"] is False


def test_read_only_parent_does_not_hide_nested_writable_mount():
    report = review(record(mount(ROOTS[0], "/media", False),
                           mount("/other/source", "/media/Movies", True)))
    item = report["containers_requiring_review"][0]
    assert "writable_destination_overlap" in item["issues"]
    assert item["mounts"][1]["source"] == "/other/source"


def test_read_only_docker_socket_is_still_administrative_access_to_review():
    report = review(record(mount("/var/run/docker.sock", "/var/run/docker.sock", False)))
    assert "socket_access_requires_review" in report["containers_requiring_review"][0]["issues"]


def test_unknown_volume_and_devices_are_not_ignored():
    report = review(record(mount("/var/lib/docker/volumes/x", "/unknown", True, "volume"),
                           device_count=1, privileged=True, cap_add=["SYS_ADMIN"]))
    issues = report["containers_requiring_review"][0]["issues"]
    assert "non_bind_writer_requires_review" in issues
    assert "device_access_review_required" in issues
    assert "privileged_container_review_required" in issues
    assert "added_capabilities_review_required" in issues


def test_similar_prefix_is_not_a_path_overlap_and_never_gives_clearance():
    report = review(record(mount("/mnt/user/media_backup", "/backup")))
    assert report["containers_requiring_review"] == []
    assert report["status"] == "review_required"
    assert report["path_resolution_verified"] is False
    assert report["snapshot_continuity_verified"] is False
    assert report["production_authorized"] is False
    assert report["blockers"]


@pytest.mark.parametrize("bad", [mount("/relative/../media", "/media"),
                                  mount(None, "/media"),
                                  {"Source": ROOTS[0], "Destination": "/media", "RW": "false", "Type": "bind"}])
def test_invalid_paths_or_missing_bind_metadata_fail_closed(bad):
    with pytest.raises(ValueError):
        review(record(bad))


@pytest.mark.parametrize("complete", [True, False])
def test_cli_requires_completion_record_without_exposing_unselected_fields(monkeypatch, capsys, complete):
    selected = record(mount(ROOTS[0], "/media"))
    selected["unselected_secret"] = "must-not-be-printed"
    content = json.dumps(selected) + "\n"
    if complete:
        content += '{"kind":"end"}\n'
    class Input:
        buffer = io.BytesIO(content.encode())
    monkeypatch.setattr("sys.stdin", Input())
    result = main(["--media-root", ROOTS[0]])
    output = capsys.readouterr().out
    assert "must-not-be-printed" not in output
    assert result == (0 if complete else 2)
    assert json.loads(output)["production_authorized"] is False


def test_single_rw_mount_is_not_misreported_as_another_overlapping_mount():
    item = review(record(mount(ROOTS[0], "/media")))["containers_requiring_review"][0]
    assert "writable_declared_media_mount" in item["issues"]
    assert "writable_destination_overlap" not in item["issues"]
    assert item["control_requirements"] == ["fence_media_write_routes", "inhibit_writer_start_or_restart"]


def test_stopped_privileged_writer_requires_start_inhibition_and_access_review():
    item = review(record(mount(ROOTS[0], "/media"), running=False,
                         restart="always", privileged=True))["containers_requiring_review"][0]
    assert "keep_stopped_writer_fenced" in item["control_requirements"]
    assert "review_elevated_host_access" in item["control_requirements"]
    assert "inhibit_writer_start_or_restart" in item["control_requirements"]


def test_read_only_socket_requires_api_fence_without_claiming_media_write_overlap():
    item = review(record(mount("/var/run/docker.sock", "/var/run/docker.sock", False)))[
        "containers_requiring_review"][0]
    assert item["control_requirements"] == ["fence_administrative_api_routes"]


def test_cache_volume_is_a_scope_question_not_an_asserted_media_writer():
    report = review(record(mount("/var/lib/docker/volumes/cache", "/cache", kind="volume")))
    item = report["containers_requiring_review"][0]
    assert item["control_requirements"] == ["resolve_non_bind_storage_scope"]
    assert "writable_declared_media_mount" not in item["issues"]
    assert report["enforcement_supported"] is False
