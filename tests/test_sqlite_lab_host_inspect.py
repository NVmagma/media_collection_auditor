"""Host-side Compose verification never authorizes writes."""
from pathlib import Path
import copy
import pytest
from scripts.sqlite_lab_host_inspect import verify_compose_layout


def config():
    return {"services": {"sqlite-lab": {
        "network_mode": "none", "read_only": True, "cap_drop": ["ALL"],
        "entrypoint": ["python"],
        "security_opt": ["no-new-privileges:true"],
        "working_dir": "/workspace",
        "tmpfs": ["/tmp:rw,nosuid,nodev,noexec,size=32m"],
        "environment": {"PYTHONPATH": "/workspace", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"},
        "user": "99:100", "image": "python:3.12-slim@sha256:" + "a" * 64,
        "volumes": [
            {"type": "bind", "source": "/mnt/user/sqlite_lab_test",
             "target": "/lab", "read_only": False,
             "bind": {"create_host_path": False}},
            {"type": "bind", "source": "/mnt/user/sqlite_lab_checkout",
             "target": "/workspace", "read_only": True,
             "bind": {"create_host_path": False}},
        ],
    }}}


def verify(value):
    return verify_compose_layout(value, Path("/mnt/user/sqlite_lab_test"),
                                 Path("/mnt/user/sqlite_lab_checkout"),
                                 expected_image="python:3.12-slim@sha256:" + "a" * 64,
                                 expected_user="99:100")


def test_expected_layout_is_only_advisory():
    result = verify(config())
    assert result["status"] == "review_required"
    assert result["authorization"] == "not_authorized"


@pytest.mark.parametrize("change", ["extra_service", "extra_mount", "wrong_source",
                                      "writable_checkout", "network", "privileged",
                                      "wrong_entrypoint", "missing_mount"])
def test_unexpected_compose_configuration_blocks(change):
    value = copy.deepcopy(config())
    service = value["services"]["sqlite-lab"]
    if change == "extra_service":
        value["services"]["production"] = {}
    elif change == "extra_mount":
        service["volumes"].append({"type": "bind", "source": "/media",
                                    "target": "/media"})
    elif change == "wrong_source":
        service["volumes"][0]["source"] = "/mnt/user/appdata"
    elif change == "writable_checkout":
        service["volumes"][1]["read_only"] = False
    elif change == "network":
        service["network_mode"] = "bridge"
    elif change == "privileged":
        service["privileged"] = True
    elif change == "wrong_entrypoint":
        service["entrypoint"] = ["sh"]
    elif change == "missing_mount":
        service["volumes"].pop()
    with pytest.raises(RuntimeError):
        verify(value)


@pytest.mark.parametrize("key,value", [("user", "0:0"), ("image", "python:latest"), ("security_opt", []), ("tmpfs", []), ("environment", {}), ("working_dir", "/")])
def test_runtime_identity_changes_block(key, value):
    candidate = config()
    candidate["services"]["sqlite-lab"][key] = value
    with pytest.raises(RuntimeError):
        verify(candidate)


def test_unraid_mount_evidence_is_review_only():
    from scripts.sqlite_lab_host_inspect import compare_unraid_mount_evidence
    mounts = [
        {"Type": "bind", "Source": "/mnt/user/sqlite_lab_test",
         "Destination": "/lab", "RW": True},
        {"Type": "bind", "Source": "/mnt/user/sqlite_lab_checkout",
         "Destination": "/workspace", "RW": False},
    ]
    probe = {"status": "blocked", "reason": "lab_mount_root_unverified",
             "authorization": "not_authorized", "production_media_inspected": False,
             "lab_mount_count": 1,
             "lab_mounts": [{"target": "/lab", "root": "/sqlite_lab_test",
                             "filesystem": "fuse.shfs", "read_only": False}]}
    lab = Path("/mnt/user/sqlite_lab_test")
    checkout = Path("/mnt/user/sqlite_lab_checkout")
    result = compare_unraid_mount_evidence(mounts, probe, lab, checkout)
    assert result["status"] == "review_required"
    assert result["authorization"] == "not_authorized"
    for change in ("wrong_source", "writable_checkout", "extra_mount",
                   "wrong_root", "nested_mount", "missing_probe"):
        changed_mounts = copy.deepcopy(mounts)
        changed_probe = copy.deepcopy(probe)
        if change == "wrong_source":
            changed_mounts[0]["Source"] = "/mnt/user/media"
        elif change == "writable_checkout":
            changed_mounts[1]["RW"] = True
        elif change == "extra_mount":
            changed_mounts.append({"Type": "bind", "Source": "/media",
                                   "Destination": "/media", "RW": True})
        elif change == "wrong_root":
            changed_probe["lab_mounts"][0]["root"] = "/media"
        elif change == "nested_mount":
            changed_probe["lab_mount_count"] = 2
        else:
            changed_probe = {}
        result = compare_unraid_mount_evidence(changed_mounts, changed_probe,
                                               lab, checkout)
        assert result["status"] == "blocked", change
        assert result["authorization"] == "not_authorized", change

