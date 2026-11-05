"""Explicit new installation and JSON backup preserve existing state."""
from copy import deepcopy
import json
import pytest
from app.json_initialize import initialize
from app.json_backup import create_backup,inspect_backup
from app.json_scan_control import admission_status
from datetime import datetime,timezone


def test_initialize_only_empty_directory_and_never_replays(tmp_path):
    root=tmp_path/'logs';root.mkdir()
    assert initialize(root)['status']=='json_tracking_initialized'
    state=json.loads((root/'auditor_state.json').read_bytes())
    assert admission_status(state,now=datetime.now(timezone.utc))['status']=='ready'
    before={p.name:p.read_bytes() for p in root.iterdir()}
    with pytest.raises(RuntimeError):initialize(root)
    assert {p.name:p.read_bytes() for p in root.iterdir()}==before


def test_json_backup_retains_unknowns_clocks_control_and_refuses_reuse(tmp_path):
    root=tmp_path/'logs';root.mkdir();initialize(root)
    path=root/'auditor_state.json';state=json.loads(path.read_bytes())
    state['extension']={'retain':42};state['first_seen']['Example']='2026-01-01T01:02:03';path.write_text(json.dumps(state))
    config=root/'auditor_config.json';config.write_text('{"private":"synthetic-secret"}')
    before=path.read_bytes();packet=tmp_path/'backup'
    result=create_backup(state_file=path,config_file=config,directory=packet)
    assert (packet/'auditor_state.json').read_bytes()==before
    assert path.read_bytes()==before and not result['restore_authorized']
    inspected=inspect_backup(directory=packet,expected_identity=result['directory_identity'],expected_fingerprint=result['backup_fingerprint'])
    assert inspected['captured_at']
    with pytest.raises(FileExistsError):create_backup(state_file=path,config_file=config,directory=packet)
