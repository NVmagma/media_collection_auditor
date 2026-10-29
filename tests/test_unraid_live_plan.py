"""The live plan changes the explicit media bind, preserving ports and credentials."""
from copy import deepcopy
from xml.etree import ElementTree as ET
import pytest
from app.config_store import DEFAULTS
from app.sqlite_live_policy import DISABLED
from test_unraid_update_production_prepare import inputs
from scripts.unraid_live_plan import live_metadata


def values():
    args=inputs();args['current']['State']['Running']=True
    args['current']['HostConfig']['CapDrop']=['ALL']
    args['image'].update(Id='sha256:'+'c'*64,RepoDigests=[args['reference']])
    args['image']['Config'].update(Entrypoint=['python','-m','app.main'],StopSignal='SIGINT',
        Labels={'io.media-collection-auditor.sqlite-activation':'scheduled-moves','org.opencontainers.image.revision':'d'*40})
    args['environment']={**DEFAULTS,**args['environment'],'DRY_RUN':'false','MAX_ACTIONS_PER_RUN':'1',
                         'SQLITE_DAILY_RUN_TIME':'02:00','SQLITE_DAILY_RUN_TIMEZONE':'America/Los_Angeles',
                         'READ_ONLY_API_SERVICE':'false',**{key:'false' for key in DISABLED}}
    args['host_media']='/native-pool/media_storage'
    return args


def test_native_rw_proposal_keeps_sqlite_clocks_paths_ports_credentials_and_original_template():
    args=values();before=deepcopy(args)
    payload,raw=live_metadata(**args);root=ET.fromstring(raw)
    assert args==before
    media=next(item for item in payload['HostConfig']['Mounts'] if item['Target']=='/media')
    assert media['Source']==args['host_media'] and media['ReadOnly'] is False
    assert payload['HostConfig']['ReadonlyRootfs'] is True
    assert payload['HostConfig']['RestartPolicy']['Name']=='no'
    assert payload['HostConfig']['PortBindings']==args['current']['HostConfig']['PortBindings']
    assert root.find("Config[@Target='/media']").get('Mode')=='rw'
    assert root.find("Config[@Target='/media']").text==args['host_media']
    assert root.findtext('Repository')==args['reference']
    env=dict(item.split('=',1) for item in payload['Env'])
    assert env['MAX_ACTIONS_PER_RUN']=='1' and env['DRY_RUN']=='false'
    assert env['INTEGRATION_API_TOKEN']==args['environment']['INTEGRATION_API_TOKEN']
    assert payload['Labels']['io.media-collection-auditor.sqlite-activation']=='scheduled-moves'
    assert root.findtext('WebUI')=='http://[IP]:[PORT:8080]/'


@pytest.mark.parametrize('change',['profile','digest','image','attempt','native-alias','native-private','native-traversal',
                                   'unsafe-policy','capabilities','root-rw','stale-template','stopped'])
def test_unreviewed_live_proposals_rejected_without_mutating_inputs(change):
    args=values()
    if change=='profile':args['image']['Config']['Labels']['io.media-collection-auditor.sqlite-activation']='preview-only'
    elif change=='digest':args['image']['RepoDigests']=[]
    elif change=='image':args['image']['Id']=args['current']['Image']
    elif change=='attempt':args['attempt']='bad'
    elif change=='native-alias':args['host_media']=args['current']['Mounts'][0]['Source']
    elif change=='native-private':args['host_media']=args['host_logs']+'/media'
    elif change=='native-traversal':args['host_media']='/native/../media'
    elif change=='unsafe-policy':args['environment']['ALLOW_FILESYSTEM_DELETE']='true'
    elif change=='capabilities':args['current']['HostConfig']['CapAdd']=['SYS_ADMIN']
    elif change=='root-rw':args['current']['HostConfig']['ReadonlyRootfs']=False
    elif change=='stale-template':args['template']=args['template'].replace(b'8089',b'8090')
    else:args['current']['State']['Running']=False
    before=deepcopy(args)
    with pytest.raises(ValueError):live_metadata(**args)
    assert args==before


def test_effective_saved_schedule_is_validated_without_rewriting_runtime_defaults():
    args=values();effective=deepcopy(args['environment'])
    args['environment']['SQLITE_DAILY_RUN_TIME']=''
    args['environment']['SQLITE_DAILY_RUN_TIMEZONE']=''
    payload,_=live_metadata(**args,effective_settings=effective)
    runtime=dict(item.split('=',1) for item in payload['Env'])
    assert runtime['SQLITE_DAILY_RUN_TIME']==''
    assert runtime['SQLITE_DAILY_RUN_TIMEZONE']==''


def test_proposal_failure_identifies_capability_guard_without_private_text():
    args=values();args['current']['HostConfig']['CapAdd']=['SYS_ADMIN'];stages=[]
    with pytest.raises(ValueError):live_metadata(**args,diagnostic=stages.append)
    assert stages[-1]=='proposal_capability_policy'


@pytest.mark.parametrize('original_drop',[None,[],['CHOWN']])
def test_new_canary_has_approved_minimal_capability_independent_of_old_preview(original_drop):
    import shlex
    args=values();args['current']['HostConfig']['CapDrop']=original_drop
    root=ET.fromstring(args['template']);root.find('ExtraParams').text='--read-only --cap-drop=CHOWN'
    args['template']=ET.tostring(root);before=deepcopy(args)
    payload,raw=live_metadata(**args)
    assert args==before
    assert payload['HostConfig']['CapDrop']==['ALL']
    assert payload['HostConfig']['CapAdd']==['DAC_OVERRIDE']
    extra=shlex.split(ET.fromstring(raw).findtext('ExtraParams'))
    assert '--cap-drop=ALL' in extra and '--cap-drop=CHOWN' not in extra
    assert '--cap-add=DAC_OVERRIDE' in extra and '--security-opt=no-new-privileges' in extra


def test_stale_template_flags_cannot_reintroduce_unreviewed_capabilities_or_restart():
    import shlex
    args=values();root=ET.fromstring(args['template'])
    root.find('ExtraParams').text='--read-only --user=123:456 --restart=always --cap-add=SYS_ADMIN --security-opt=seccomp=unconfined'
    args['template']=ET.tostring(root)
    payload,raw=live_metadata(**args)
    extra=shlex.split(ET.fromstring(raw).findtext('ExtraParams'))
    assert '--user=0:0' in extra and '--restart=no' in extra
    assert [value for value in extra if value.startswith('--cap-add=')]==['--cap-add=DAC_OVERRIDE']
    assert not any('seccomp=unconfined' in value or 'SYS_ADMIN' in value for value in extra)
    assert payload['HostConfig']['CapAdd']==['DAC_OVERRIDE']


def test_unrepresented_privileged_template_flags_are_refused():
    args=values();root=ET.fromstring(args['template'])
    root.find('ExtraParams').text='--read-only --privileged';args['template']=ET.tostring(root)
    with pytest.raises(ValueError,match='Unsupported template runtime argument'):live_metadata(**args)
