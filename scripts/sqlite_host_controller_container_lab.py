"""Launch only a new cached-image, host-mount-free controller test container."""
import argparse
import io
import tarfile
import json
from pathlib import Path
import re

from scripts.sqlite_offline_dispatch_container_lab import command,source_archive


def run(image,*,native=False):
    if not re.fullmatch(r'sha256:[0-9a-f]{64}',image):raise ValueError('Full cached image ID required')
    metadata=json.loads(command('docker','image','inspect',image))
    if len(metadata)!=1 or metadata[0]['Id']!=image or metadata[0]['Config'].get('Volumes'):
        raise RuntimeError('Exact cached image without declared volumes required')
    checkout=Path(__file__).resolve().parents[1]
    source=source_archive(checkout)
    if native:
        output=io.BytesIO(source)
        path=checkout/'scripts/sqlite_host_controller_native.sh'
        if path.resolve()!=path:raise RuntimeError('Canonical native launcher required')
        content=path.read_bytes()
        with tarfile.open(fileobj=output,mode='a') as archive:
            entry=tarfile.TarInfo('scripts/sqlite_host_controller_native.sh')
            entry.size=len(content);entry.mode=0o444
            archive.addfile(entry,io.BytesIO(content))
        source=output.getvalue()
    fixture_module='scripts.sqlite_host_controller_native_lab' if native else 'scripts.sqlite_host_controller_lab'
    container=command('docker','create','--pull=never','--network','none',
        '--hostname','mca-host-controller-fixture','--user','0:0','--read-only',
        '--cap-drop','ALL','--security-opt','no-new-privileges','--pids-limit','64','--memory','768m' if native else '256m',
        '--tmpfs','/fixture:rw,exec,nosuid,nodev,size=512m' if native else '/fixture:rw,noexec,nosuid,nodev,size=32m','--interactive','--workdir','/fixture',
        '--entrypoint','/usr/local/bin/python3',image,'-I','-S','-B','-c',
        'import sys,os,tarfile,io,subprocess; '
        'tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read()),mode="r:").extractall("/fixture/code",filter="data"); '
        'os.chdir("/fixture/code"); '
        'subprocess.run([sys.executable,"-B","-m",'+repr(fixture_module)+','
        '"--root","/fixture/control"],check=True,timeout=90)').decode().strip()
    if not re.fullmatch('[0-9a-f]{64}',container):raise RuntimeError('Full new container ID required')
    try:
        output=command('docker','start','--attach','--interactive',container,input=source).decode()
        state=json.loads(command('docker','inspect','--format','{{json .State}}',container))
        if state['ExitCode']!=0 or state['OOMKilled']:raise RuntimeError('Controller fixture failed')
        return output
    finally:command('docker','rm','--force',container)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',required=True)
    parser.add_argument('--native',action='store_true')
    args=parser.parse_args()
    print(run(args.image,native=args.native),end='')
