"""Actual CLI with verified backup, disposable media and loopback GET services."""
import json
from pathlib import Path
import subprocess
import sys

import pytest
from scripts import unraid_live_update_backup as backup
from scripts import json_comparison_candidate as candidate
from scripts import json_readonly_rehearsal as rehearsal
from test_unraid_live_update_backup import options, fingerprint
from test_json_readonly_scan import local
from test_json_scan_collection import services


@pytest.fixture
def comparison(tmp_path,local,services):
    source,values,movie,show,episode = local
    server,snapshot,inventory,remote_settings = services
    values.update(remote_settings)
    server.items['Movie'] = [{**server.items['Movie'][0],'Path':str(movie/'movie.mkv')}]
    server.items['Series'] = [{**server.items['Series'][0],'Path':str(show)}]
    server.catalogs['movie'] = [{'id':1,'path':str(movie),'monitored':True}]
    server.catalogs['series'] = [{'id':2,'path':str(show),'monitored':True}]
    fixture = tmp_path/'backup-fixture'; fixture.mkdir()
    packet,state,inputs,kwargs,control = options(fixture)
    kwargs['read_snapshot'] = lambda: (json.loads(source.read_bytes()),11)
    kwargs['container']['Config']['Env'] = [key+'='+value for key,value in values.items()]
    inputs['saved-config.json'] = (json.dumps({'ENABLE_TV':True,'FAVORITES_TRIGGER_KEEP':True,
        'future_metadata':{'private':'synthetic-private-extension'}}).encode(),(1,2))
    backup.capture_backup(**kwargs)
    parent = tmp_path/'comparison'; parent.mkdir(mode=0o700)
    root,_ = candidate.prepare_candidate(backup=packet,backup_identity=kwargs['expected_identity'],
        fingerprint=fingerprint(packet),parent=parent)
    return root,packet,server


def test_actual_cli_gets_services_and_never_changes_tracking_or_claims(comparison):
    root,packet,server = comparison
    before = {path:path.read_bytes() for parent in (root,packet) for path in parent.iterdir()}
    result = subprocess.run([sys.executable,'-B','-m','scripts.json_readonly_rehearsal',
        '--comparison',str(root),'--backup',str(packet),'--fingerprint',fingerprint(packet)],
        capture_output=True,text=True,timeout=30)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['status'] == 'json_readonly_rehearsal_observed'
    assert report['source_snapshot_revision'] == 11 and report['scanned_titles'] == 2
    assert len(report['proposed_moves']) == 2
    assert report['tracking_bytes_unchanged'] and report['scan_claims_unchanged']
    assert not report['media_actions_performed'] and report['arr_updates_sent'] == 0
    assert report['settings_basis'] == 'selected_backup' and not report['freshness_verified']
    assert all(path.read_bytes() == raw for path,raw in before.items())
    assert all(method == 'GET' for method,_ in server.calls)
    assert 'synthetic-private' not in result.stdout and 'synthetic-arr-token' not in result.stdout


@pytest.mark.parametrize('change', ['state','claims','manifest'])
def test_changed_comparison_refused_before_remote_reads(comparison,change):
    root,packet,server = comparison
    filename = {'state':'auditor_state.json','claims':'scan-claims-archive.json','manifest':'comparison-complete.json'}[change]
    (root/filename).write_bytes(b'{}')
    with pytest.raises(RuntimeError): rehearsal.run(comparison=root,backup=packet,fingerprint=fingerprint(packet))
    assert not server.calls


def test_cli_failure_does_not_print_private_exception_or_paths(monkeypatch,capsys):
    monkeypatch.setattr(sys,'argv',['rehearsal','--comparison','/private-comparison',
        '--backup','/private-backup','--fingerprint','0'*64])
    monkeypatch.setattr(rehearsal,'run',lambda **k: (_ for _ in ()).throw(RuntimeError('private-token-path-response')))
    assert rehearsal.main() == 2
    report = json.loads(capsys.readouterr().out)
    assert report['reason'] == 'input_or_collection_unavailable'
    assert 'private' not in str(report)


def test_local_only_mode_never_requests_services_and_preserves_snapshot(comparison):
    root,packet,server = comparison
    before = (root/'auditor_state.json').read_bytes()
    report = rehearsal.run(comparison=root,backup=packet,fingerprint=fingerprint(packet),local_only=True)
    assert report['status'] == 'json_readonly_rehearsal_observed'
    assert report['network_enabled'] is False and report['rehearsal_scope'] == 'local_inventory_only'
    assert report['scanned_titles'] == 2 and report['proposed_moves'] == []
    assert report['library_status'][0]['inventory_complete']
    assert not server.calls and (root/'auditor_state.json').read_bytes() == before


def test_cli_failure_reports_last_fixed_stage_without_exception_text(monkeypatch,capsys):
    monkeypatch.setattr(sys,'argv',['rehearsal','--comparison','/test',
        '--backup','/test-backup','--fingerprint','0'*64,'--local-only'])
    def fail(**kwargs):
        kwargs['observer']('captured_settings')
        raise ValueError('synthetic-private-configuration')
    monkeypatch.setattr(rehearsal,'run',fail)
    assert rehearsal.main() == 2
    report = json.loads(capsys.readouterr().out)
    assert report['diagnostic_stage'] == 'captured_settings' and report['error_type'] == 'ValueError'
    assert 'synthetic-private' not in str(report)
