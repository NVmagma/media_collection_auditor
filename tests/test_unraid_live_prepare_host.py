"""Shell preflight consumes real-shaped Docker newlines; all Docker calls mocked."""
import os
from pathlib import Path
import subprocess
import sys

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/unraid_live_prepare_host.sh'


def invoke(tmp_path,*,extra=False,filesystem='btrfs'):
    checkout=tmp_path/'checkout';(checkout/'scripts').mkdir(parents=True)
    script=checkout/'scripts'/SCRIPT.name;script.write_bytes(SCRIPT.read_bytes())
    packet=tmp_path/'packet';packet.mkdir()
    base=tmp_path/'base';base.mkdir()
    media=tmp_path/'media';media.mkdir()
    binaries=tmp_path/'bin';binaries.mkdir()
    marker=tmp_path/'helper-ran'
    shim='#!'+sys.executable+'''\nimport os,sys
from pathlib import Path
name=Path(sys.argv[0]).name; args=sys.argv[1:]
if name=='uname': print('Linux')
elif name=='id': print('0')
elif name=='stat': print('1:2')
elif name=='findmnt': print(os.environ['FILESYSTEM'])
elif name=='git':
    if 'branch' in args: print('feature/interface-api')
elif name=='docker':
    if args[:2]==['context','inspect']: print('unix:///var/run/docker.sock')
    elif args[:2]==['image','inspect']:
        form=args[args.index('--format')+1] if '--format' in args else ''
        if form=='{{.Id}}': print('sha256:'+'b'*64)
        elif 'Volumes' in form: print('null')
        elif 'Labels' in form: print('scheduled-moves')
        else: print('[{"Id":"sha256:'+'b'*64+'"}]')
    elif args[0]=='inspect':
        form=args[args.index('--format')+1]
        if '.Type' in form:
            print('bind /app/logs\\nbind /media\\nbind /sqlite-control\\n'+('bind /unexpected\\n' if os.environ['EXTRA']=='true' else ''))
        elif '.RW' in form: print('false')
        elif '.Source' in form: print(os.environ['MEDIA'])
        else: print('a'*64)
    elif args[0]=='run':
        sys.stdin.read();Path(os.environ['MARKER']).write_text('fixture-only')
        print('{"status":"mock_helper_executed"}')
    else: raise SystemExit(3)
'''
    for name in ('uname','id','stat','findmnt','git','docker'):
        path=binaries/name;path.write_text(shim);path.chmod(0o755)
    env={**os.environ,'PATH':str(binaries)+os.pathsep+os.environ['PATH'],
         'MEDIA':str(media),'MARKER':str(marker),'EXTRA':str(extra).lower(),'FILESYSTEM':filesystem}
    env.pop('DOCKER_HOST',None);env.pop('DOCKER_CONTEXT',None)
    result=subprocess.run(['bash',str(script),'sha256:'+'b'*64,str(packet),'c'*64,str(base),str(media)],env=env,text=True,capture_output=True,timeout=20)
    return result,marker,base


def test_docker_trailing_blank_line_does_not_reject_exact_three_binds(tmp_path):
    result,marker,base=invoke(tmp_path)
    assert result.returncode==0,result.stdout+result.stderr
    assert marker.exists()
    assert 'status=live_files_ready_not_started' in result.stdout
    assert len(list(base.iterdir()))==1


def test_extra_bind_still_blocks_with_clear_reason_before_writes(tmp_path):
    result,marker,base=invoke(tmp_path,extra=True)
    assert result.returncode==2
    assert 'reason=current_mount_layout_mismatch' in result.stderr
    assert 'step=current_container_preflight' in result.stderr
    assert not marker.exists() and not list(base.iterdir())


def test_user_share_filesystem_rejected_before_any_preparation(tmp_path):
    result,marker,base=invoke(tmp_path,filesystem='fuse.shfs')
    assert result.returncode==2
    assert 'reason=native_filesystem_required' in result.stderr
    assert not marker.exists() and not list(base.iterdir())
