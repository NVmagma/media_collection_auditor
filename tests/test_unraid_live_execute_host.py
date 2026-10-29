"""Host check is a read-only data preflight; explicit actions require the fingerprint."""
import hashlib,json,os,subprocess,sys
from pathlib import Path
import pytest

@pytest.mark.parametrize('action',['check','deploy'])
def test_host_mounts_and_explicit_fingerprint(tmp_path,action):
    checkout=tmp_path/'checkout';(checkout/'scripts').mkdir(parents=True)
    source=Path(__file__).resolve().parents[1]/'scripts/unraid_live_execute_host.sh'
    script=checkout/'scripts'/source.name;script.write_bytes(source.read_bytes())
    roots={key:tmp_path/key for key in ('prepared','review','packet','native','old_logs','old_control','shared')}
    for path in roots.values():path.mkdir()
    for name in ('logs','control'):(roots['prepared']/name).mkdir()
    (roots['review']/'review-complete.json').write_bytes(b'{}')
    binaries=tmp_path/'bin';binaries.mkdir();log=tmp_path/'calls.jsonl'
    shim='#!'+sys.executable+'''\nimport json,os,sys
from pathlib import Path
name=Path(sys.argv[0]).name;args=sys.argv[1:]
if name=='uname':print('Linux')
elif name=='id':print('0')
elif name=='stat':print('1:2')
elif name=='git':
    if 'branch' in args:print('feature/interface-api')
elif name=='docker':
    with open(os.environ['CALLS'],'a') as stream:stream.write(json.dumps(args)+'\\n')
    if args[:2]==['context','inspect']:print('unix:///var/run/docker.sock')
    elif args[:2]==['image','inspect']:
        if 'Volumes' in args[args.index('--format')+1]:print('null')
        else:print('sha256:'+'b'*64)
    elif args[0]=='info':print('fixture-daemon')
    elif args[0]=='inspect':
        form=args[args.index('--format')+1]
        if '.Type' in form:print('bind /app/logs\\nbind /media\\nbind /sqlite-control\\n')
        else:
            key='old_logs' if '/app/logs' in form else 'old_control' if '/sqlite-control' in form else 'shared'
            print(os.environ[key])
    elif args[0]=='run':
        if '-c' in args:print('a'*64)
        else:print('{"status":"fixture_check"}')
    else:raise SystemExit(4)
'''
    for name in ('uname','id','stat','git','docker'):
        path=binaries/name;path.write_text(shim);path.chmod(0o755)
    env={**os.environ,**{key:str(value) for key,value in roots.items()},'PATH':str(binaries)+os.pathsep+os.environ['PATH'],'CALLS':str(log)}
    env.pop('DOCKER_HOST',None);env.pop('DOCKER_CONTEXT',None)
    result=subprocess.run(['bash',str(script),action,'ghcr.io/nvmagma/media_collection_auditor@sha256:'+'d'*64,
        str(roots['prepared']),str(roots['review']),str(roots['packet']),'c'*64,str(roots['native'])],
        env=env,text=True,capture_output=True,timeout=15)
    calls=[json.loads(line) for line in log.read_text().splitlines()]
    runs=[call for call in calls if call[0]=='run']
    if action=='deploy':
        assert result.returncode==2 and 'explicit_review_fingerprint_required' in result.stderr
        assert len(runs)==1
        return
    assert result.returncode==0,result.stdout+result.stderr
    assert len(runs)==2
    command=runs[-1];mounts=[command[index+1] for index,value in enumerate(command) if value=='--mount']
    assert f'type=bind,src={roots["native"]},dst=/media,readonly' in mounts
    assert f'type=bind,src={roots["shared"]},dst=/shared-media,readonly' in mounts
    assert all(value.endswith(',readonly') for value in mounts if 'docker.sock' not in value)
    assert command[command.index('--network')+1]=='none'
    assert 'scripts.unraid_live_execute' in command
    assert hashlib.sha256(b'{}').hexdigest() in result.stdout
