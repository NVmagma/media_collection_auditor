"""Private JSON replacement preparation preserves clocks and the latest claim."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from scripts import json_cutover_prepare as prepare
from scripts import unraid_live_update_backup as backup
from test_unraid_live_update_backup import options,fingerprint
from test_json_worker_migration import archive,ZONE,NOW
from app.json_scan_control import KEY,admission_status

REVISION='f'*40


def setup(tmp_path,claims=None,environment=()):
    packet,state,inputs,kwargs,control=options(tmp_path)
    kwargs['container']['Config']['Env'] += ['DRY_RUN=false','MAX_ACTIONS_PER_RUN=2',
        'TZ='+ZONE,'SQLITE_DAILY_RUN_TIMEZONE='+ZONE,'SQLITE_DAILY_RUN_TIME=02:00',
        'AUDITOR_STATE_BACKEND=sqlite','SQLITE_STATE_FILE=/sqlite-control/release/state.db',
        'EXPERIMENTAL_SQLITE_RECOVERY_VIEW=false','ENABLE_TV=true']
    kwargs['container']['Config']['Env']+=list(environment)
    kwargs['read_claims']=lambda:(deepcopy(archive() if claims is None else claims),('synthetic',1))
    backup.capture_backup(**kwargs)
    root=tmp_path/'new-private'; root.mkdir(mode=0o700)
    image=dict(Id='sha256:'+'e'*64,Config=dict(Labels={
        'org.opencontainers.image.revision':REVISION,'io.media-collection-auditor.worker':'json-serialized'},
        Entrypoint=['python','-B','-m','app.main'],Cmd=None,Volumes=None,StopSignal='SIGINT',
        Env=['AUDITOR_WORKER_MODE=json_serialized','AUDITOR_STATE_BACKEND=json','DRY_RUN=true','MAX_ACTIONS_PER_RUN=10']))
    return state,dict(backup=packet,backup_identity=kwargs['expected_identity'],backup_fingerprint=fingerprint(packet),
        root=root,root_identity=(root.stat().st_dev,root.stat().st_ino),candidate_image=image,source_revision=REVISION)


def test_latest_snapshot_unknowns_clocks_claims_and_settings_are_preserved(tmp_path):
    state,args=setup(tmp_path); packet=args['backup']; before={p.name:p.read_bytes() for p in packet.iterdir()}
    report=prepare.prepare(**args); root=args['root']
    actual=json.loads((root/'logs/auditor_state.json').read_bytes())
    assert {key:value for key,value in actual.items() if key!=KEY}==state
    assert admission_status(actual,now=NOW)['retry_after_seconds']==2400
    assert json.loads((root/'scan-claims-archive.json').read_bytes())==archive()
    assert (root/'source-tracking.json').read_bytes()==before['tracking-snapshot.json']
    saved=json.loads((root/'logs/auditor_config.json').read_bytes())
    assert saved=={**json.loads(before['saved-config.json']),'MAX_ACTIONS_PER_RUN':'10'}
    env=dict(line.split('=',1) for line in (root/'runtime.env').read_text().splitlines())
    assert env['AUDITOR_STATE_BACKEND']=='json' and env['AUDITOR_WORKER_MODE']=='json_serialized'
    assert env['MAX_ACTIONS_PER_RUN']=='10' and env['PRIVATE']=='private-secret'
    assert 'SQLITE_STATE_FILE' not in env and 'EXPERIMENTAL_SQLITE_RECOVERY_VIEW' not in env
    assert report['per_library_action_limit']==5 and not report['deployment_authorized']
    assert report['tracking_preserved'] and report['scan_cooldown_preserved']
    assert not report['backup_freshness_verified'] and not report['writer_quiescence_verified']
    assert 'private-secret' not in json.dumps(report)
    assert all(p.read_bytes()==before[p.name] for p in packet.iterdir())
    assert all(p.stat().st_mode & 0o777==0o600 for p in root.rglob('*') if p.is_file())
    assert (root/prepare.COMPLETE).is_file()


@pytest.mark.parametrize('change',['corrupt','fingerprint','image','image_env','revision','overlap'])
def test_bad_selection_never_writes_preparation(tmp_path,change):
    _,args=setup(tmp_path); original_root=args['root']
    if change=='corrupt': (args['backup']/'tracking-snapshot.json').write_bytes(b'{}')
    elif change=='fingerprint': args['backup_fingerprint']='0'*64
    elif change=='image': args['candidate_image']['Config']['Entrypoint']=['python','-m','app.main']
    elif change=='image_env': args['candidate_image']['Config']['Env']=[]
    elif change=='revision': args['source_revision']='a'*40
    else: args['root']=args['backup']
    with pytest.raises((RuntimeError,ValueError)): prepare.prepare(**args)
    assert list(original_root.iterdir())==[]


@pytest.mark.parametrize('phase',['after_request','before_control','after_control','before_completion'])
def test_interruption_retains_partial_directory_and_refuses_replay(tmp_path,monkeypatch,phase):
    _,args=setup(tmp_path)
    def stop(current):
        if current==phase: raise RuntimeError('synthetic stop')
    monkeypatch.setattr(prepare,'_boundary',stop)
    with pytest.raises(RuntimeError): prepare.prepare(**args)
    assert not (args['root']/prepare.COMPLETE).exists()
    before={str(p.relative_to(args['root'])):p.read_bytes() for p in args['root'].rglob('*') if p.is_file()}
    monkeypatch.setattr(prepare,'_boundary',lambda _:None)
    with pytest.raises(RuntimeError): prepare.prepare(**args)
    assert before=={str(p.relative_to(args['root'])):p.read_bytes() for p in args['root'].rglob('*') if p.is_file()}


def test_prepared_state_changed_at_completion_is_not_accepted(tmp_path,monkeypatch):
    _,args=setup(tmp_path)
    def change(phase):
        if phase=='before_completion': (args['root']/'logs/auditor_state.json').write_bytes(b'{}')
    monkeypatch.setattr(prepare,'_boundary',change)
    with pytest.raises(RuntimeError): prepare.prepare(**args)
    assert not (args['root']/prepare.COMPLETE).exists()


def test_replaced_log_directory_is_never_initialized(tmp_path,monkeypatch):
    _,args=setup(tmp_path); replacement=[]
    def change(phase):
        if phase=='before_control':
            logs=args['root']/'logs'; logs.rename(args['root']/'retained-logs'); logs.mkdir(mode=0o700)
            (logs/'auditor_state.json').write_bytes((args['root']/'retained-logs/auditor_state.json').read_bytes())
            replacement.append((logs/'auditor_state.json').read_bytes())
    monkeypatch.setattr(prepare,'_boundary',change)
    with pytest.raises(RuntimeError): prepare.prepare(**args)
    assert (args['root']/'logs/auditor_state.json').read_bytes()==replacement[0]
    assert sorted(p.name for p in (args['root']/'logs').iterdir())==['auditor_state.json']
    assert not (args['root']/prepare.COMPLETE).exists()


def test_incomplete_claim_cannot_reset_cooldown_or_write_candidate(tmp_path):
    _,args=setup(tmp_path,claims={'present':True,'entries':{'a'*64+'.json':''}})
    with pytest.raises(ValueError): prepare.prepare(**args)
    assert list(args['root'].iterdir())==[]


@pytest.mark.parametrize('setting',['ALLOW_PERMANENT_DELETE=true','ALLOW_CROSS_FILESYSTEM_MOVES=true',
                                   'PYTHONSTARTUP=/unreviewed.py'])
def test_unsafe_source_policy_is_not_silently_replaced(tmp_path,setting):
    _,args=setup(tmp_path,environment=[setting])
    with pytest.raises(ValueError): prepare.prepare(**args)
    assert list(args['root'].iterdir())==[]
