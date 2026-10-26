"""Local cached-image Linux mount rehearsal; no host mounts or service access."""
import argparse
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile


def command(*args, **kwargs):
    result=subprocess.run(args,capture_output=True,timeout=180,**kwargs)
    if result.returncode:
        raise RuntimeError('Disposable command failed: '+result.stderr.decode(errors='replace')[-2000:])
    return result.stdout


def source_archive(checkout):
    output=io.BytesIO()
    with tarfile.open(fileobj=output,mode='w') as archive:
        for folder in ('app','scripts'):
            for path in sorted((checkout/folder).rglob('*.py')):
                if path.is_symlink() or path.resolve()!=path:
                    raise RuntimeError('Canonical source files required')
                data=path.read_bytes()
                info=tarfile.TarInfo(str(path.relative_to(checkout)))
                info.size=len(data);info.mode=0o444
                archive.addfile(info,io.BytesIO(data))
        marker=b'DISPOSABLE DISPATCH CONTAINER ONLY\n'
        info=tarfile.TarInfo('dispatch-container-fixture')
        info.size=len(marker);info.mode=0o444
        archive.addfile(info,io.BytesIO(marker))
    return output.getvalue()


def run(image):
    if not re.fullmatch(r'sha256:[0-9a-f]{64}',image):
        raise ValueError('Full cached image ID required; no tags or pulls')
    checkout=Path(__file__).resolve().parents[1]
    source=source_archive(checkout)
    metadata=json.loads(command('docker','image','inspect',image))
    if (len(metadata)!=1 or metadata[0]['Id']!=image
            or metadata[0]['Config'].get('Volumes')):
        raise RuntimeError('Exact cached image without declared volumes required')
    # /fixture is container tmpfs. No bind, device, socket or host namespace.
    container=command('docker','create','--pull=never','--network','none',
        '--hostname','mca-dispatch-fixture','--user','0:0','--read-only','--cap-drop','ALL',
        '--cap-add','SYS_ADMIN','--security-opt','no-new-privileges',
        '--security-opt','seccomp=unconfined','--security-opt','apparmor=unconfined',
        '--pids-limit','64','--memory','256m','--tmpfs','/fixture:rw,exec,nosuid,nodev,size=32m',
        '--interactive','--workdir','/fixture','--entrypoint','/usr/local/bin/python3',image,
        '-B','-c',
        'import subprocess,sys,tarfile,io,os; '
        'tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read()),mode="r:").extractall("/fixture/code",filter="data"); '
        'os.chdir("/fixture/code"); '
        '[subprocess.run([sys.executable,"-B","-m","scripts.sqlite_offline_dispatch_guest_lab",'
        '"--root","/fixture/"+name]+flags,check=True,timeout=120) '
        'for name,flags in [("full",[]),("partial",["--partial"])]]').decode().strip()
    if not re.fullmatch('[0-9a-f]{64}',container):raise RuntimeError('Full new container ID required')
    try:
        result=command('docker','start','--attach','--interactive',container,input=source).decode()
        state=json.loads(command('docker','inspect','--format','{{json .State}}',container))
        if state['ExitCode']!=0 or state['OOMKilled']:
            raise RuntimeError('Disposable container failed: '+result[-2000:])
        return result
    finally:
        # Only this newly created container is removed, including on timeout.
        command('docker','rm','--force',container)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',required=True)
    print(run(parser.parse_args().image),end='')
