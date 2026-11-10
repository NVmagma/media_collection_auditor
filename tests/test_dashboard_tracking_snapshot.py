"""Read tracking once and give each display its own copy."""
import json
import pytest
from app.dashboard_tracking_snapshot import read_json_dashboard_snapshot
from app.tracking_schema import SECTIONS


def state():
    value = {section: {} for section in SECTIONS}
    value["first_seen"]["Example"] = "2024-01-01T00:00:00"
    value["legacy"] = {"nested": ["caf\u00e9"]}
    return value


def test_json_snapshot_is_captured_once_and_detached(tmp_path):
    path = tmp_path / "state.json"
    original = state()
    path.write_text(json.dumps(original))
    snapshot = read_json_dashboard_snapshot(path)
    consumer = snapshot.state
    consumer["legacy"]["nested"].append("mutation")
    path.write_text("{}")
    assert snapshot.state == original
    assert snapshot.metadata["storage_authority"] == "json"
    assert snapshot.revision is None


@pytest.mark.parametrize("raw", ['[]', '{"first_seen":[]}', '{"x":1,"x":2}',
    '{"first_seen":{"Example":"bad timestamp"}}', '{"unknown":NaN}'])
def test_invalid_json_tracking_is_visible_error(tmp_path, raw):
    path = tmp_path / "state.json"
    path.write_text(raw)
    with pytest.raises(RuntimeError, match="tracking state is unreadable"):
        read_json_dashboard_snapshot(path)


def test_interrupted_missing_json_is_not_empty_installation(tmp_path):
    (tmp_path / ".auditor_state_interrupted.tmp").write_text("partial")
    with pytest.raises(RuntimeError, match="tracking state is unreadable"):
        read_json_dashboard_snapshot(tmp_path / "missing.json")


def test_legacy_missing_sections_are_not_rewritten(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"legacy":{"preserve":true}}')
    assert read_json_dashboard_snapshot(path).state == {"legacy": {"preserve": True}}
    assert read_json_dashboard_snapshot(tmp_path / "fresh.json").state == {}
