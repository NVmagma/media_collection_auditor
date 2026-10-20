"""Host-side Compose verification never authorizes writes."""
from pathlib import Path
import copy
import pytest
from scripts.sqlite_lab_host_inspect import verify_compose_layout


def config():
    return {"services": {"sqlite-lab": {
        "network_mode": "none", "read_only": True, "cap_drop": ["ALL"],
        "entrypoint": ["python"],\n        "security_opt": ["no-new-privileges:true"],\n        "working_dir": "/workspace",\n        "tmpfs": ["/tmp:rw,nosuid,nodev,noexec,size=32m"],\n        "environment": {"PYTHONPATH": "/workspace", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"},\n        "user": "99:100", "image": "python:3.12-slim@sha256:" + "a" * 64,
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
                                 Path("/mnt/user/sqlite_lab_checkout"),\n                                 expected_image="python:3.12-slim@sha256:" + "a" * 64,\n                                 expected_user="99:100")


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
