"""Read-only Unraid lab mount diagnostic tests."""
from scripts.sqlite_lab_mount_probe import inspect_lab_mount_report


def test_root_mount_reports_only_advisory_evidence():
    info = ("20 1 8:1 / / rw - overlay overlay rw\\n"
            "21 20 0:45 / /lab rw - fuse.shfs shfs rw\\n")
    result = inspect_lab_mount_report(info)
    assert result["status"] == "observed_unverified"
    assert result["authorization"] == "not_authorized"
    assert result["lab_mounts"] == [{
        "target": "/lab", "root": "/", "filesystem": "fuse.shfs",
        "read_only": False,
    }]


def test_subdirectory_bind_remains_blocked_without_exposing_host_source():
    info = ("20 1 8:1 / / rw - overlay overlay rw\\n"
            "21 20 0:45 /sqlite_lab_test /lab rw - fuse.shfs /mnt/user rw\\n")
    result = inspect_lab_mount_report(info)
    assert result["status"] == "blocked"
    assert result["reason"] == "lab_mount_root_unverified"
    assert result["authorization"] == "not_authorized"
    assert "/mnt/user" not in str(result)


def test_nested_mount_and_malformed_input_fail_closed():
    info = ("21 20 0:45 / /lab rw - fuse.shfs shfs rw\\n"
            "22 21 0:46 / /lab/other rw - ext4 secret rw\\n")
    result = inspect_lab_mount_report(info)
    assert result["status"] == "blocked"
    assert result["reason"] == "nested_lab_mount"
    assert result["lab_mount_count"] == 2
    assert inspect_lab_mount_report("garbage")["status"] == "blocked"
