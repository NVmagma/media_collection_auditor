"""Mount namespace inspection never grants recovery authority."""
import pytest
from app.sqlite_recovery_mountinfo import inspect_mountinfo

INFO = ("20 1 8:1 / / rw - ext4 /dev/root rw\n"
        "21 20 8:2 / /lab rw - ext4 /dev/lab rw\n")


def test_local_mount_observation_is_not_identity_proof():
    result = inspect_mountinfo("/lab/fixture", INFO)
    assert result["mount_identity"] == "local_namespace_observed_unverified"
    assert result["authorization"] == "not_authorized"
    assert "/dev/lab" not in str(result)


@pytest.mark.parametrize("path,data,reason", [
    ("relative", INFO, "invalid_path"),
    ("/lab/../lab", INFO, "invalid_path"),
    ("/lab", "", "mountinfo_unavailable"),
    ("/lab", "bad line", "mountinfo_malformed"),
    ("/lab", INFO + "21 20 8:2 / /lab rw - ext4 /dev/lab rw\n", "ambiguous_mount"),
    ("/lab", "21 20 8:2 / /lab\\040name rw - ext4 /dev/lab rw\n", "mountinfo_escaped_path_unverified"),
])
def test_invalid_or_ambiguous_mountinfo_fails_closed(path, data, reason):
    result = inspect_mountinfo(path, data)
    assert result["reason"] == reason
    assert result["authorization"] == "not_authorized"
    assert result["mount_identity"] == "unverified"
