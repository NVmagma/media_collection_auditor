"""Cutover proposals preserve metadata and reject drift without service authority."""
from copy import deepcopy
import json
from xml.etree import ElementTree as ET
import pytest
from scripts import json_cutover_review as review
from scripts.json_cutover_source_review import compare_source
from scripts.json_cutover_prepare import prepare
from scripts.unraid_live_plan import live_metadata
from scripts.unraid_live_update_backup import load_backup_payloads
from test_unraid_live_plan import values
from test_json_cutover_prepare import setup


def proposal_args():
    original=values(); payload,template=live_metadata(**original)
    current=dict(Id='b'*64,Image=original['image']['Id'],Name='/media_collection_auditor',State={'Running':True},
        Config={key:value for key,value in payload.items() if key!='HostConfig'},HostConfig=payload['HostConfig'],
        Mounts=[dict(Type='bind',Destination=row['Target'],Source=row['Source'],RW=not row['ReadOnly'],Propagation='rprivate')
                for row in payload['HostConfig']['Mounts']])
    image=deepcopy(original['image']); image['Id']='sha256:'+'e'*64
    image['Config'].update(Entrypoint=['python','-B','-m','app.main'],Labels={
        'org.opencontainers.image.revision':'f'*40,'io.media-collection-auditor.worker':'json-serialized'})
    environment=dict(original['environment'],AUDITOR_WORKER_MODE='json_serialized',AUDITOR_STATE_BACKEND='json',MAX_ACTIONS_PER_RUN='10')
    environment.pop('SQLITE_STATE_FILE',None)
    return dict(current=current,image=image,template=template,environment=environment,
        host_logs='/new-json-private/logs',reference=original['reference'],attempt='f'*64)


def test_two_bind_proposal_preserves_media_port_secrets_security_and_icon():
    args=proposal_args(); before=deepcopy(args)
    payload,xml=review.metadata(**args); root=ET.fromstring(xml)
    assert args==before
    assert payload['HostConfig']['PortBindings']==args['current']['HostConfig']['PortBindings']
    assert payload['HostConfig']['ReadonlyRootfs'] is True
    assert payload['HostConfig']['CapAdd']==['DAC_OVERRIDE']
    assert {row['Target'] for row in payload['HostConfig']['Mounts']}=={'/media','/app/logs'}
    assert payload['HostConfig']['Mounts'][0]['Source']==next(item['Source'] for item in args['current']['Mounts'] if item['Destination']=='/media')
    assert dict(value.split('=',1) for value in payload['Env'])['INTEGRATION_API_TOKEN']==args['environment']['INTEGRATION_API_TOKEN']
    assert root.find("Config[@Type='Path'][@Target='/sqlite-control']") is None
    assert root.find("Config[@Type='Variable'][@Target='SQLITE_STATE_FILE']") is None
    assert root.findtext('Icon')==ET.fromstring(args['template']).findtext('Icon')
    assert root.findtext('Repository')==args['reference']
    assert payload['Entrypoint']==['python','-B','-m','app.main']
    assert not any('sqlite-activation' in key for key in payload['Labels'])


@pytest.mark.parametrize('change',['overlap','digest','port','extra','capability','privileged','duplicate','mount'])
def test_unreviewed_proposals_are_refused(change):
    args=proposal_args()
    if change=='overlap': args['host_logs']=args['current']['Mounts'][0]['Source']+'/private'
    elif change=='digest': args['image']['RepoDigests']=[]
    elif change=='port': args['template']=args['template'].replace(b'8089',b'8090')
    elif change=='extra': args['template']=args['template'].replace(b'--read-only',b'--read-only --entrypoint=/other')
    elif change=='capability': args['current']['HostConfig']['CapAdd']=['SYS_ADMIN']
    elif change=='privileged': args['current']['HostConfig']['Privileged']=True
    elif change=='duplicate': args['current']['Mounts'].append(deepcopy(args['current']['Mounts'][0]))
    else: args['current']['Mounts'][0]['RW']=False
    before=deepcopy(args)
    with pytest.raises((ValueError,RuntimeError)): review.metadata(**args)
    assert args==before


def prepared_args(tmp_path):
    _,args=setup(tmp_path); prepare(**args)
    payloads,receipt=load_backup_payloads(directory=args['backup'],expected_identity=args['backup_identity'],expected_fingerprint=args['backup_fingerprint'])
    return args,dict(files=review.private_files(args['root']),payloads=payloads,receipt=receipt,image=args['candidate_image'],fingerprint=args['backup_fingerprint'])


def test_prepared_verification_preserves_all_state_and_requires_no_writes(tmp_path):
    args,kwargs=prepared_args(tmp_path)
    before=deepcopy(kwargs)
    env,result=review.verify_prepared(**kwargs)
    assert kwargs==before and env['MAX_ACTIONS_PER_RUN']=='10' and result['tracking_preserved']
    assert review.private_files(args['root'])==kwargs['files']


@pytest.mark.parametrize('change',['state','config','archive','env','image','revision','receipt'])
def test_prepared_drift_cannot_be_adopted(tmp_path,change):
    _,kwargs=prepared_args(tmp_path)
    names={'state':'logs/auditor_state.json','config':'logs/auditor_config.json','archive':'scan-claims-archive.json','env':'runtime.env'}
    if change in names: kwargs['files'][names[change]]+=b' '
    elif change=='image': kwargs['image']['Id']='sha256:'+'9'*64
    elif change=='revision': kwargs['image']['Config']['Labels']['org.opencontainers.image.revision']='9'*40
    else:
        value=json.loads(kwargs['files'][review.COMPLETE]);value['source_snapshot_revision']+=1
        kwargs['files'][review.COMPLETE]=json.dumps(value).encode()
    with pytest.raises((ValueError,RuntimeError)): review.verify_prepared(**kwargs)


def source_args(tmp_path):
    _,kwargs=prepared_args(tmp_path)
    payloads,receipt=kwargs['payloads'],kwargs['receipt']; current=json.loads(payloads['current.inspect.json'])
    current['State']={'Running':True}
    payloads['current.inspect.json']=json.dumps(current).encode()
    return dict(payloads=payloads,receipt=receipt,current=current,validate=lambda:None,
        snapshot=lambda:(json.loads(payloads['tracking-snapshot.json']),receipt['snapshot_revision']),
        inputs=lambda:{name:payloads[name] for name in ('saved-config.json','retained-source.json','current-binding.json')},
        claims=lambda:json.loads(payloads['daily-claims.json']))


def test_source_observation_does_not_claim_running_writer_is_quiescent(tmp_path):
    args=source_args(tmp_path); args['current']['State']['Running']=True
    result=compare_source(**args)
    assert result['backup_matches_current_observation'] and not result['writer_quiescence_verified']
    assert not result['media_actions_performed']


@pytest.mark.parametrize('change',['tracking','claim','config','pending','concurrent','validator'])
def test_stale_or_unresolved_source_blocks_review(tmp_path,change):
    args=source_args(tmp_path)
    if change in ('tracking','pending'):
        state,revision=args['snapshot']();state['changed']=True;args['snapshot']=lambda:(state,revision)
    elif change=='claim': args['claims']=lambda:{'present':True,'entries':{}}
    elif change=='config':
        inputs=args['inputs']();inputs['saved-config.json']=b'{}';args['inputs']=lambda:inputs
    elif change=='validator': args['validate']=lambda:(_ for _ in ()).throw(RuntimeError('blocked'))
    else:
        original=args['snapshot'];calls=[]
        def changing():
            state,revision=original();calls.append(True)
            if len(calls)>1: state['changed']=True
            return state,revision
        args['snapshot']=changing
    with pytest.raises(RuntimeError): compare_source(**args)


def complete_review_args(tmp_path):
    from test_unraid_live_update_backup import options,fingerprint
    from test_json_worker_migration import archive
    from scripts.unraid_live_update_backup import capture_backup
    packet,state,inputs,kwargs,control=options(tmp_path)
    proposal=proposal_args()
    kwargs.update(container=proposal['current'],template=proposal['template'],read_claims=lambda:(archive(),('fixed',1)))
    capture_backup(**kwargs)
    root=tmp_path/'json-preparation';root.mkdir(mode=0o700)
    image=proposal['image']
    image['Config'].update(Env=['AUDITOR_WORKER_MODE=json_serialized','AUDITOR_STATE_BACKEND=json','DRY_RUN=true','MAX_ACTIONS_PER_RUN=10'],
        Cmd=None,Volumes=None,StopSignal='SIGINT')
    prepare(backup=packet,backup_identity=(packet.stat().st_dev,packet.stat().st_ino),backup_fingerprint=fingerprint(packet),
        root=root,root_identity=(root.stat().st_dev,root.stat().st_ino),candidate_image=image,source_revision='f'*40)
    output=tmp_path/'review';output.mkdir(mode=0o700)
    return dict(backup=packet,backup_identity=(packet.stat().st_dev,packet.stat().st_ino),fingerprint=fingerprint(packet),
        prepared=root,current=proposal['current'],image=image,templates=[('managed.xml',proposal['template'])],
        host_logs=str(root/'logs'),reference=proposal['reference'],output=output,output_identity=(output.stat().st_dev,output.stat().st_ino))


def test_completed_review_has_no_service_or_template_authority(tmp_path):
    args=complete_review_args(tmp_path)
    before=review.private_files(args['prepared'])
    result=review.review(**args)
    assert result['status']=='json_cutover_review_prepared' and result['mount_count']==2
    assert not result['deployment_authorized'] and not result['writer_quiescence_verified']
    assert result['per_library_action_limit']==5
    assert 'private-secret' not in json.dumps(result)
    assert (args['output']/'review-complete.json').exists()
    assert review.private_files(args['prepared'])==before


@pytest.mark.parametrize('change',['duplicate','stale_template','state','current','interrupted','identical_replacement'])
def test_review_drift_never_completes(tmp_path,monkeypatch,change):
    args=complete_review_args(tmp_path)
    if change=='duplicate': args['templates']*=2
    elif change=='stale_template': args['templates']=[('managed.xml',args['templates'][0][1]+b' ')]
    elif change=='state': (args['prepared']/'logs/auditor_state.json').write_bytes(b'{}')
    elif change=='current': args['current']['Config']['Env'].append('UNREVIEWED=true')
    else:
        write=review._write_private
        def changed(fd,name,raw):
            write(fd,name,raw)
            if name=='proposed-container.json':
                if change=='interrupted': raise RuntimeError('synthetic interruption')
                path=args['prepared']/'logs/auditor_state.json'
                data=path.read_bytes();path.rename(path.with_name('retained.json'));path.write_bytes(data);path.chmod(0o600)
        monkeypatch.setattr(review,'_write_private',changed)
    with pytest.raises((ValueError,RuntimeError)): review.review(**args)
    assert not (args['output']/'review-complete.json').exists()
