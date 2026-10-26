"""Host orchestration tests use command shims; no real Docker or /mnt writes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'sqlite_preview_service_host.sh'
BASH = shutil.which('bash')
MODERN_BASH = BASH and int(subprocess.check_output([BASH, '-c', 'echo "${BASH_VERSINFO[0]}"'], text=True)) >= 4
pytestmark = pytest.mark.skipif(not MODERN_BASH, reason='Host launcher requires Linux/modern Bash; exercised in CI')
IMAGE = 'sha256:' + 'd' * 64
REVISION = 'a' * 40
REFERENCE = 'ghcr.io/nvmagma/media_collection_auditor@sha256:' + 'e' * 64

SHIM = r'''
import json,os,sys
from pathlib import Path
tool=Path(sys.argv[0]).name; args=sys.argv[1:]; scenario=os.environ['SCENARIO']
if tool=='uname': print('Linux')
elif tool=='id': print('0')
elif tool=='stat': print('0:700' if '%u:%a' in args else '1:2')
elif tool=='git':
    if args[:1]==['-c']: args=args[2:]
    if args[:2]==['branch','--show-current']: print('feature/sqlite')
    elif args[:2]==['rev-parse','--verify']: print('a'*40)
    elif args[:1]==['archive']: sys.stdout.buffer.write(b'trusted-fixture-archive')
    elif args[:1]==['diff'] and scenario=='dirty': raise SystemExit(1)
elif tool=='docker':
    with open(os.environ['CALLS'],'a') as log: log.write(json.dumps(args)+'\n')
    if args[:2]==['context','show']: print('default')
    elif args[:2]==['context','inspect']: print('unix:///var/run/docker.sock')
    elif args[:2]==['image','inspect']:
        fmt=args[args.index('--format')+1]
        if '.RepoDigests' in fmt: print('ghcr.io/nvmagma/media_collection_auditor@sha256:'+'e'*64)
        elif '.Id' in fmt:
            print('sha256:'+('f'*64 if scenario=='wrong_digest' and '@sha256:' in args[-1] else 'd'*64))
        elif 'sqlite-activation' in fmt: print('preview-only')
        elif 'image.revision' in fmt: print('b'*40)
        elif 'Volumes' in fmt: print('null')
    elif args[:1]==['run']:
        sys.stdin.buffer.read()
        operation=next(item for item in ('review-sha','control-path','reference','review') if item in args)
        if scenario=='request_failure':
            print('c'*64); raise SystemExit(47)
        if operation=='review-sha': print('c'*64)
        elif operation=='control-path': print(os.environ['CONTROL'])
        elif operation=='reference': print('ghcr.io/nvmagma/media_collection_auditor@sha256:'+'e'*64)
        else: print('{"status":"review_only"}')
    elif args[:1]==['push'] and scenario=='push_failure': raise SystemExit(31)
    elif args[:1]==['info']: print('fixture-daemon')
    elif args[:1]==['create']: print('f'*64)
    elif args[:1]==['start']:
        sys.stdin.buffer.read()
        if scenario=='controller_failure': raise SystemExit(41)
        print('{"status":"fixture_controller_finished"}')
    elif args[:1]==['inspect']: print('0 false')
'''


@pytest.fixture
def host(tmp_path):
    root = tmp_path.resolve(); binaries = root / 'bin'; binaries.mkdir()
    for name in ('uname','id','stat','git','docker'):
        path = binaries / name
        path.write_text('#!' + sys.executable + '\n' + SHIM)
        path.chmod(0o755)
    packet = root / 'packet'; packet.mkdir(mode=0o700)
    env = {key:value for key,value in os.environ.items() if not key.startswith('DOCKER_')}
    env.update(PATH=str(binaries)+os.pathsep+env.get('PATH',''), CALLS=str(root/'calls.jsonl'),
               CONTROL=str(root/'control'), SCENARIO='normal')
    def run(mode='review', scenario='normal', **updates):
        result = subprocess.run([BASH,str(SCRIPT),mode,IMAGE,str(packet),'1'*64,REVISION],
            env={**env,'SCENARIO':scenario,**updates},capture_output=True,text=True)
        calls = [json.loads(line) for line in (root/'calls.jsonl').read_text().splitlines()] if (root/'calls.jsonl').exists() else []
        return result,calls
    return root,run


def test_review_uses_only_ephemeral_readonly_request_without_publication_or_control(host):
    root,run=host; result,calls=run()
    assert result.returncode==0,result.stderr
    assert not (root/'control').exists()
    assert not any(args[0] in ('tag','push','create','start','stop','rename') for args in calls)
    request=next(args for args in calls if args[0]=='run')
    assert 'none' in request and '--read-only' in request
    assert any('dst=/packet,readonly' in arg for arg in request)


def test_failed_request_even_with_valid_looking_stdout_never_publishes(host):
    root,run=host; result,calls=run('deploy','request_failure')
    assert result.returncode!=0
    assert not any(args[0] in ('tag','push','create','start') for args in calls)
    assert not (root/'control').exists()


def test_failed_registry_push_never_creates_control_or_controller(host):
    root,run=host; result,calls=run('deploy','push_failure')
    assert result.returncode!=0
    assert any(args[0]=='push' for args in calls)
    assert not any(args[0] in ('create','start') for args in calls)
    assert not (root/'control').exists()


def test_wrong_published_digest_never_creates_control_or_controller(host):
    root,run=host; result,calls=run('deploy','wrong_digest')
    assert result.returncode!=0
    assert not (root/'control').exists()
    assert not any(args[0] in ('create','start') for args in calls)


def test_remote_docker_context_is_rejected_before_any_image_or_service_operation(host):
    _,run=host; result,calls=run('deploy',DOCKER_HOST='tcp://outside.invalid:2375')
    assert result.returncode!=0 and calls==[]


def test_occupied_control_root_is_preserved_without_publication(host):
    root,run=host; (root/'control').mkdir(); (root/'control'/'retained').write_text('keep')
    result,calls=run('deploy')
    assert result.returncode!=0 and (root/'control'/'retained').read_text()=='keep'
    assert not any(args[0] in ('tag','push','create','start') for args in calls)


def test_full_host_handoff_preserves_mount_scopes_and_publishes_only_versioned_tag(host):
    root,run=host; result,calls=run('deploy')
    assert result.returncode==0,result.stderr
    tag=next(args for args in calls if args[0]=='tag')[-1]
    assert tag.startswith('ghcr.io/nvmagma/media_collection_auditor:sqlite-preview-')
    assert not tag.endswith((':latest',':feature-sqlite'))
    create=next(args for args in calls if args[0]=='create')
    assert '--read-only' in create and 'DAC_OVERRIDE' in create and 'CHOWN' not in create
    assert any('src=/mnt/user/media_storage,dst=/media,readonly' in arg for arg in create)
    assert REFERENCE in create
    assert not any(args[0] in ('stop','rename','restart','update') for args in calls)
    assert [args for args in calls if args[0]=='rm']==[['rm','--force','f'*64]]


def test_controller_failure_retains_control_without_retry_or_automatic_rollback(host):
    root,run=host; result,calls=run('deploy','controller_failure')
    assert result.returncode!=0 and (root/'control').is_dir()
    assert sum(args[0]=='start' for args in calls)==1
    assert not any(args[0] in ('stop','rename','restart','update') for args in calls)


def test_explicit_rollback_uses_retained_reference_without_tag_push_or_directory_creation(host):
    root,run=host; (root/'control').mkdir()
    result,calls=run('rollback')
    assert result.returncode==0,result.stderr
    assert not any(args[0] in ('tag','push') for args in calls)
    create=next(args for args in calls if args[0]=='create')
    assert 'rollback' in create and REFERENCE in create
