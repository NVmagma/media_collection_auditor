"""JSON handoff stops on uncertainty and never restores advanced JSON tracking."""
from copy import deepcopy
import hashlib
import json
import os
from types import SimpleNamespace
import pytest
from scripts import json_cutover_execute as execute
from scripts import json_cutover_review as review
from scripts.sqlite_preview_service_fixture import Engine,NEW_ID
from scripts.sqlite_preview_service import LABEL
from test_json_cutover_review import complete_review_args


def identity(path): return (path.stat().st_dev,path.stat().st_ino)


@pytest.fixture
def selected(tmp_path):
    args=complete_review_args(tmp_path);review.review(**args)
    templates=tmp_path/'templates';templates.mkdir(mode=0o700)
    path=templates/'managed.xml';path.write_bytes(args['templates'][0][1]);path.chmod(0o600)
    engine=Engine(args['current']);engine.containers={args['current']['Id']:deepcopy(args['current'])}
    engine.selected_image=deepcopy(args['image'])
    def created(item):
        item['Image']=args['image']['Id']
        for row in item['Mounts']: row.update(Type='bind',Propagation='rprivate')
    engine.on_create=created
    checks=[]
    def source_check(engine,**kwargs): checks.append(kwargs['current']['State']['Running'])
    options=dict(engine=engine,review=args['output'],review_identity=identity(args['output']),
        review_fingerprint=hashlib.sha256((args['output']/'review-complete.json').read_bytes()).hexdigest(),
        backup=args['backup'],backup_identity=args['backup_identity'],backup_fingerprint=args['fingerprint'],
        prepared=args['prepared'],templates=templates,host_backup=str(args['backup']),host_checkout=str(tmp_path),source_check=source_check,data_check=lambda *args,**kwargs:None)
    return SimpleNamespace(args=args,options=options,engine=engine,checks=checks,template=path)


def run(case,action='deploy',**kwargs):
    update=execute.SelectedJSON(**case.options);fd=os.open(case.args['output'],os.O_RDONLY|os.O_DIRECTORY)
    try: return execute.run_selected(update,action=action,parent=fd,health=lambda **kwargs:None,**kwargs)
    finally: os.close(fd)


def test_check_does_not_stop_or_write_production(selected):
    before=review.private_files(selected.args['prepared']); template=selected.template.read_bytes()
    result=run(selected,'check')
    assert result['status']=='json_handoff_preflight_verified'
    assert selected.engine.calls==[] and selected.checks==[True]
    assert not result['media_actions_authorized']
    assert review.private_files(selected.args['prepared'])==before and selected.template.read_bytes()==template
    assert not (selected.args['output']/'service-request.json').exists()


def test_deploy_rechecks_after_stop_and_installs_only_reviewed_template(selected):
    result=run(selected)
    assert result['status']=='json_worker_cutover_complete' and result['storage_authority']=='json'
    assert result['maximum_actions']==10 and result['per_library_action_limit']==5
    assert not result['permanent_deletion_authorized']
    assert selected.checks==[True,False]
    assert [row[0] for row in selected.engine.calls]==['stop','rename','create','start']
    assert not selected.engine.inspect(selected.args['current']['Id'])['State']['Running']
    assert selected.template.read_bytes()==(selected.args['output']/'proposed-template.xml').read_bytes()
    assert (selected.args['output']/'service-request.json').exists()


@pytest.mark.parametrize('operation',['stop','rename','create','start'])
def test_lost_ack_is_retained_without_retry_or_automatic_restoration(selected,operation):
    selected.engine.lose_ack=operation
    with pytest.raises(TimeoutError): run(selected)
    before=deepcopy(selected.engine.calls)
    with pytest.raises((RuntimeError,FileExistsError)): run(selected)
    assert selected.engine.calls==before
    assert selected.template.read_bytes()==selected.args['templates'][0][1]


def test_changed_source_after_stop_refuses_before_archive_or_creation(selected):
    def stale(engine,**kwargs):
        if not kwargs['current']['State']['Running']: raise RuntimeError('Source changed')
    selected.options['source_check']=stale
    with pytest.raises(RuntimeError): run(selected)
    assert [row[0] for row in selected.engine.calls]==['stop']
    assert selected.template.read_bytes()==selected.args['templates'][0][1]


def test_source_changes_before_stop_cause_no_service_actions(selected):
    selected.options['source_check']=lambda *args,**kwargs:(_ for _ in ()).throw(RuntimeError('Stale'))
    with pytest.raises(RuntimeError): run(selected)
    assert selected.engine.calls==[]
    assert not (selected.args['output']/'service-request.json').exists()


@pytest.mark.parametrize('change',['state','settings','review','template','image','mount'])
def test_preflight_refuses_changed_pinned_inputs(selected,change):
    if change=='state': (selected.args['prepared']/'logs/auditor_state.json').write_bytes(b'{}')
    elif change=='settings': (selected.args['prepared']/'logs/auditor_config.json').write_bytes(b'{}')
    elif change=='review': (selected.args['output']/'proposed-template.xml').write_bytes(b'<Container/>')
    elif change=='template': selected.template.write_bytes(selected.template.read_bytes()+b' ')
    elif change=='image': selected.engine.selected_image['Id']='sha256:'+'9'*64
    else: selected.engine.containers[selected.args['current']['Id']]['Mounts'][0]['RW']=False
    with pytest.raises((ValueError,RuntimeError)): run(selected,'check')
    assert selected.engine.calls==[]


@pytest.mark.parametrize('change',['entrypoint','capability','extra_mount','cmd'])
def test_created_container_deviation_refuses_before_start(selected,change):
    original=selected.engine.on_create
    def changed(item):
        original(item)
        if change=='entrypoint': item['Config']['Entrypoint']=['python','-m','app.main']
        elif change=='capability': item['HostConfig']['CapAdd']=['SYS_ADMIN']
        elif change=='extra_mount': item['Mounts'].append(dict(Type='bind',Source='/other',Destination='/extra',RW=True))
        else: item['Config']['Cmd']=['different']
    selected.engine.on_create=changed
    with pytest.raises(RuntimeError): run(selected)
    assert 'start' not in [row[0] for row in selected.engine.calls]
    assert selected.template.read_bytes()==selected.args['templates'][0][1]


def test_failed_health_preserves_old_container_and_original_template(selected):
    update=execute.SelectedJSON(**selected.options);fd=os.open(selected.args['output'],os.O_RDONLY|os.O_DIRECTORY)
    def failure(**kwargs): raise RuntimeError('Not ready')
    try:
        with pytest.raises(RuntimeError): execute.run_selected(update,action='deploy',parent=fd,health=failure)
    finally: os.close(fd)
    assert not selected.engine.inspect(selected.args['current']['Id'])['State']['Running']
    assert selected.template.read_bytes()==selected.args['templates'][0][1]
    assert selected.engine.inspect(NEW_ID)['State']['Running']


def test_explicit_unchanged_recovery_retains_replacement_and_restores_template(selected,monkeypatch):
    run(selected)
    monkeypatch.setattr('scripts.sqlite_preview_service.verify_http_health',lambda **kwargs:None)
    result=run(selected,'recover')
    assert result['status']=='unchanged_json_cutover_previous_recovered'
    assert selected.engine.inspect(selected.args['current']['Id'])['State']['Running']
    assert not selected.engine.inspect(NEW_ID)['State']['Running']
    assert selected.template.read_bytes()==selected.args['templates'][0][1]


@pytest.mark.parametrize('change',['clock','pending','settings'])
def test_new_json_activity_blocks_stale_recovery_before_any_service_change(selected,change):
    run(selected);before=deepcopy(selected.engine.calls)
    path=selected.args['prepared']/('logs/auditor_config.json' if change=='settings' else 'logs/auditor_state.json')
    value=json.loads(path.read_bytes())
    if change=='settings': value['ENABLE_TV']='false'
    elif change=='clock': value['first_seen']['latest']='2026-11-03T00:00:00+00:00'
    else: value['json_worker_control']['journal']={'uncertain':True}
    path.write_text(json.dumps(value));path.chmod(0o600)
    with pytest.raises(RuntimeError): run(selected,'recover')
    assert selected.engine.calls==before and selected.engine.inspect(NEW_ID)['State']['Running']


def test_source_helper_has_only_readonly_inputs_and_no_network_or_socket(selected):
    payload=execute.source_helper_payload(current=selected.args['current'],host_backup=str(selected.args['backup']),
        host_checkout='/reviewed/checkout',backup_identity=selected.args['backup_identity'],fingerprint=selected.args['fingerprint'],request_id='a'*64)
    host=payload['HostConfig']
    assert payload['Image']==selected.args['current']['Image']
    assert host['NetworkMode']=='none' and host['ReadonlyRootfs'] and host['CapDrop']==['ALL'] and host['CapAdd']==[]
    assert all(row['ReadOnly'] for row in host['Mounts'])
    assert {row['Target'] for row in host['Mounts']}=={'/media','/app/logs','/sqlite-control','/backup','/review-source'}
    assert not host.get('PortBindings') and not host.get('VolumesFrom')
    assert payload['Cmd']==['--backup-identity',':'.join(map(str,selected.args['backup_identity'])),'--fingerprint',selected.args['fingerprint']]


def readiness():
    counts=dict(first_seen=554,queued=7,keep_seen=15,in_removal=2,arr_sync_pending=0)
    summary=dict(storage_authority='json',tracking_counts=dict(waiting=554,holding=7,keep=15,removal=2,arr_sync_pending=0),
        pending_operation_present=False,read_only=True,freshness_verified=False)
    audit=dict(storage_authority='json',worker_mode='json_serialized',execution_mode='scheduled_live_moves',
        execution_blocked=False,running=False,queued=False,next_run='2026-11-04T10:00:00+00:00',maximum_actions=10,
        per_library_action_limit=5,minimum_live_scan_interval_seconds=3600,permanent_deletion_authorized=False)
    return summary,audit,counts


def test_health_requires_json_five_library_slots_and_exact_tracking_counts():
    execute.health_contract(*readiness())


@pytest.mark.parametrize('change',['backend','counts','pending','deletion','limit','mode','blocked','running'])
def test_health_cannot_accept_wrong_backend_or_unsafe_or_missing_values(change):
    summary,audit,counts=readiness()
    if change=='backend': summary['storage_authority']='sqlite'
    elif change=='counts': summary['tracking_counts']['waiting']=0
    elif change=='pending': summary['pending_operation_present']=True
    else:
        key={'deletion':'permanent_deletion_authorized','limit':'maximum_actions','mode':'worker_mode','blocked':'execution_blocked','running':'running'}[change]
        audit[key]=True if change in ('deletion','blocked','running') else None
    with pytest.raises(RuntimeError): execute.health_contract(summary,audit,counts)


@pytest.mark.parametrize('failure',[None,'exit','create_ack','start_ack','identity'])
def test_source_helper_never_retries_or_deletes_failed_or_unknown_containers(selected,failure):
    class HelperEngine:
        def __init__(self): self.calls=[];self.value=None
        def create(self,name,payload):
            self.calls.append('create')
            self.value=dict(Id='7'*64,Image=payload['Image'],Config={'Labels':payload['Labels']},
                State=dict(Status='created',Running=False,ExitCode=0,OOMKilled=False,Error=''))
            if failure=='create_ack': raise TimeoutError('lost')
            return '7'*64
        def inspect(self,identity):
            value=deepcopy(self.value)
            if failure=='identity': value['Id']='8'*64
            return value
        def start(self,identity):
            self.calls.append('start');self.value['State'].update(Status='exited',ExitCode=2 if failure=='exit' else 0)
            if failure=='start_ack': raise TimeoutError('lost')
        def request(self,method,route,**kwargs):
            assert method=='DELETE' and route=='/containers/'+'7'*64
            self.calls.append('delete')
    engine=HelperEngine()
    kwargs=dict(current=selected.args['current'],host_backup=str(selected.args['backup']),host_checkout='/reviewed/checkout',
        backup_identity=selected.args['backup_identity'],fingerprint=selected.args['fingerprint'])
    if failure:
        with pytest.raises((RuntimeError,TimeoutError)): execute.check_source(engine,**kwargs)
        assert 'delete' not in engine.calls
    else:
        execute.check_source(engine,**kwargs)
        assert engine.calls==['create','start','delete']


def test_controller_sigkill_after_old_stop_requires_explicit_unchanged_recovery(selected,monkeypatch,tmp_path):
    import multiprocessing,signal
    snapshot=tmp_path/'fixture-engine.json'
    original_effect=selected.engine.effect
    def persist(method,identity):
        original_effect(method,identity)
        snapshot.write_text(json.dumps(dict(containers=selected.engine.containers,calls=selected.engine.calls)))
        snapshot.chmod(0o600)
    selected.engine.effect=persist
    def source_check(engine,**kwargs):
        if not kwargs['current']['State']['Running']: os.kill(os.getpid(),signal.SIGKILL)
    selected.options['source_check']=source_check
    child=multiprocessing.get_context('fork').Process(target=lambda:run(selected))
    child.start();child.join(10)
    if child.is_alive(): child.kill();child.join(5);pytest.fail('Controller death boundary not reached')
    assert child.exitcode==-signal.SIGKILL
    retained=json.loads(snapshot.read_text());selected.engine.containers=retained['containers'];selected.engine.calls=retained['calls']
    assert [row[0] for row in selected.engine.calls]==['stop']
    assert not selected.engine.inspect(selected.args['current']['Id'])['State']['Running']
    assert selected.template.read_bytes()==selected.args['templates'][0][1]
    before=deepcopy(selected.engine.calls)
    selected.options['source_check']=lambda *args,**kwargs:None
    with pytest.raises((RuntimeError,FileExistsError)): run(selected)
    assert selected.engine.calls==before  # No automatic continuation or restoration.
    monkeypatch.setattr('scripts.sqlite_preview_service.verify_http_health',lambda **kwargs:None)
    result=run(selected,'recover')
    assert result['status']=='unchanged_json_cutover_previous_recovered'
    assert selected.engine.inspect(selected.args['current']['Id'])['State']['Running']
    assert [row[0] for row in selected.engine.calls]==['stop','start']


@pytest.mark.parametrize('target',[None,'9'*64])
def test_data_helper_uses_only_readonly_prepared_or_exact_replacement_binds(target):
    payload=execute.data_helper_payload(image_id='sha256:'+'e'*64,host_logs='/private-json/logs',target=target,
        expected_identity=(1,2),expected_hashes={'auditor_state.json':'a'*64,'auditor_config.json':'b'*64},request_id='a'*64)
    host=payload['HostConfig']
    assert host['NetworkMode']=='none' and host['ReadonlyRootfs'] and host['CapDrop']==['ALL']
    assert not host.get('PortBindings') and not host.get('Binds')
    if target: assert host['VolumesFrom']==[target+':ro'] and not host.get('Mounts')
    else: assert host['Mounts']==[dict(Type='bind',Source='/private-json/logs',Target='/app/logs',ReadOnly=True,BindOptions={'Propagation':'rprivate'})]


@pytest.mark.parametrize('change',[None,'state','config','replaced_directory','symlink','hardlink'])
def test_executed_data_helper_checks_bytes_and_directory_identity(tmp_path,change):
    import subprocess,sys
    logs=tmp_path/'logs';logs.mkdir(mode=0o700)
    for name in ('auditor_state.json','auditor_config.json'):
        path=logs/name;path.write_bytes(b'{"synthetic":true}');path.chmod(0o600)
    payload=execute.data_helper_payload(image_id='sha256:'+'e'*64,host_logs=str(logs),target=None,
        expected_identity=identity(logs),expected_hashes={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in logs.iterdir()},request_id='a'*64)
    if change in ('state','config'): (logs/('auditor_state.json' if change=='state' else 'auditor_config.json')).write_bytes(b'{"changed":true}')
    elif change=='replaced_directory':
        logs.rename(tmp_path/'retained'); logs.mkdir(mode=0o700)
        for path in (tmp_path/'retained').iterdir(): (logs/path.name).write_bytes(path.read_bytes())
    elif change in ('symlink','hardlink'):
        path=logs/'auditor_state.json';path.rename(logs/'retained.json')
        if change=='symlink': path.symlink_to(logs/'retained.json')
        else: os.link(logs/'retained.json',path)
    # Only redirect the fixed mount point into this disposable test directory.
    code=payload['Entrypoint'][-1].replace("'/app/logs'",repr(str(logs)))
    result=subprocess.run([sys.executable,'-B','-c',code,*payload['Cmd']],capture_output=True)
    assert (result.returncode==0)==(change is None)


def test_docker_resolved_data_mismatch_stops_before_start(selected):
    def changed(engine,**kwargs):
        if kwargs['target'] is not None: raise RuntimeError('Actual mount differs')
    selected.options['data_check']=changed
    with pytest.raises(RuntimeError): run(selected)
    assert [row[0] for row in selected.engine.calls]==['stop','rename','create']
    assert selected.template.read_bytes()==selected.args['templates'][0][1]


def test_recovery_checks_actual_replacement_data_before_stopping_it(selected):
    run(selected);before=deepcopy(selected.engine.calls)
    def changed(engine,**kwargs):
        if kwargs['target'] is not None: raise RuntimeError('Actual replacement advanced')
    selected.options['data_check']=changed
    with pytest.raises(RuntimeError): run(selected,'recover')
    assert selected.engine.calls==before and selected.engine.inspect(NEW_ID)['State']['Running']


@pytest.mark.parametrize('interrupted',['stopped','journal'])
def test_check_refuses_interrupted_transaction_instead_of_reporting_ready(selected,interrupted):
    if interrupted=='stopped': selected.engine.containers[selected.args['current']['Id']]['State']['Running']=False
    else: (selected.args['output']/'service-request.json').write_bytes(b'{}')
    with pytest.raises(RuntimeError): run(selected,'check')
    assert selected.engine.calls==[]
