"""Host review mounts all existing inputs read-only and never controls services."""
import json,os,subprocess,sys
from pathlib import Path
import pytest

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/unraid_live_review_host.sh'


@pytest.mark.parametrize('filesystem',['btrfs','fuse.shfs'])
def test_review_launcher_keeps_native_and_shared_inputs_readonly(tmp_path,filesystem):
    checkout=tmp_path/'checkout';(checkout/'scripts').mkdir(parents=True)
    script=checkout/'scripts'/SCRIPT.name;script.write_bytes(SCRIPT.read_bytes())
    roots={key:tmp_path/key for key in ('prepared','packet','native','old_logs','old_control','shared')}
    for path in roots.values():path.mkdir()
    for name in ('logs','control'):(roots['prepared']/name).mkdir()
    binaries=tmp_path/'bin';binaries.mkdir();log=tmp_path/'calls.jsonl'
    shim='#!'+sys.executable+'''\nimport json,os,sys
from pathlib import Path
name=Path(sys.argv[0]).name;args=sys.argv[1:]
if name=='uname':print('Linux')
elif name=='id':print('0')
elif name=='stat':print('1:2')
elif name=='findmnt':print(os.environ['FILESYSTEM'])
elif name=='git':pass
elif name=='docker':
    with open(os.environ['CALLS'],'a') as stream:stream.write(json.dumps(args)+'\\n')
    if args[:2]==['context','inspect']:print('unix:///var/run/docker.sock')
    elif args[:2]==['image','inspect']:
        if '--format' not in args:print('[{}]')
        elif 'Volumes' in args[args.index('--format')+1]:print('null')
        else:print('sha256:'+'b'*64)
    elif args[0]=='inspect':
        if '--format' not in args:print('[{}]')
        else:
            form=args[args.index('--format')+1]
            if '.Type' in form:print('bind /app/logs\\nbind /media\\nbind /sqlite-control\\n')
            elif '.Source' in form:
                key='old_logs' if '/app/logs' in form else 'old_control' if '/sqlite-control' in form else 'shared'
                print(os.environ[key])
            else:print('a'*64)
    elif args[0]=='run':sys.stdin.read();print('{"status":"fixture_review_only"}')
    else:raise SystemExit(4)
'''
    for name in ('uname','id','stat','findmnt','git','docker'):
        path=binaries/name;path.write_text(shim);path.chmod(0o755)
    env={**os.environ,**{key:str(value) for key,value in roots.items()},'PATH':str(binaries)+os.pathsep+os.environ['PATH'],
         'FILESYSTEM':filesystem,'CALLS':str(log)}
    env.pop('DOCKER_HOST',None);env.pop('DOCKER_CONTEXT',None)
    result=subprocess.run(['bash',str(script),'sha256:'+'b'*64,str(roots['prepared']),str(roots['packet']),
                           'c'*64,str(roots['native']),'ghcr.io/nvmagma/media_collection_auditor@sha256:'+'d'*64],
                          env=env,text=True,capture_output=True,timeout=15)
    calls=[json.loads(line) for line in log.read_text().splitlines()]
    assert all(call[0] in ('context','image','inspect','run') for call in calls)
    runs=[call for call in calls if call[0]=='run']
    if filesystem!='btrfs':
        assert result.returncode==2 and not runs
        assert 'native_filesystem_required' in result.stderr
        return
    assert result.returncode==0,result.stdout+result.stderr
    assert len(runs)==1
    run=runs[0];mounts=[run[index+1] for index,value in enumerate(run) if value=='--mount']
    assert all('docker.sock' not in mount for mount in mounts)
    assert f'type=bind,src={roots["native"]},dst=/media,readonly' in mounts
    assert f'type=bind,src={roots["shared"]},dst=/shared-media,readonly' in mounts
    writable=[mount for mount in mounts if not mount.endswith(',readonly')]
    assert len(writable)==1 and writable[0].endswith(',dst=/review')
    assert 'status=live_review_capture_complete' in result.stdout
