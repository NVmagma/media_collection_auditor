"""NFSv4 kernel-client delayed-write test inside the disposable Linux VM only.

Never run on Tower. The guest has its own kernel; no production export is used.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import uuid


def require_guest():
    if (sys.platform!='linux' or os.geteuid()!=0 or socket.gethostname()!='mca-writer-fixture'
            or Path('/var/lib/cloud/data/instance-id').read_text().strip()!='mca-writer-fixture'):
        raise RuntimeError('Dedicated disposable guest required; never run on Tower')


def command(*args,timeout=15):
    result=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
    if result.returncode:
        raise RuntimeError('Guest NFS fixture command failed: '+args[0]+': '+result.stderr[-800:])
    return result.stdout


def require_helpers_alive(*processes):
    if any(process.poll() is not None for process in processes):
        raise RuntimeError('Guest recovery/mount helper exited; inspect retained logs')


def client(root,version):
    require_guest()
    root=Path(root)
    target=root/'mounted'
    command('mount','-t','nfs','-o',f'vers={version},proto=tcp,port=2049,hard,timeo=10,retrans=2',
            '192.0.2.1:/',str(target),timeout=30)
    mounted=True
    fd=None
    try:
        entries=[line for line in Path('/proc/self/mounts').read_text().splitlines()
                 if line.split()[1]==str(target)]
        if len(entries)!=1 or 'vers='+version not in entries[0].split()[3].split(','):
            raise RuntimeError('Requested real NFS minor version not established')
        (root/'mount-observed').write_text(entries[0])
        fd=os.open(target/'payload',os.O_RDWR)
        os.pwrite(fd,b'BEFORE!\n',0);os.fsync(fd)
        (root/'client-ready').touch()
        deadline=time.monotonic()+30
        while not (root/'write-request').exists():
            if time.monotonic()>deadline: raise RuntimeError('Guest client request timeout')
            time.sleep(.05)
        (root/'write-attempted').touch()
        os.pwrite(fd,b'PENDING\n',0)
        (root/'write-returned').touch()
        os.fsync(fd)
        (root/'fsync-completed').touch()
        os.close(fd);fd=None
        command('umount',str(target),timeout=15);mounted=False
        (root/'client-unmounted').touch()
    finally:
        if fd is not None: os.close(fd)
        if mounted:
            # Never count forced/lazy unmount as acceptance. On failure, retain
            # evidence; the enclosing disposable VM can be powered off safely.
            subprocess.run(['umount',str(target)],capture_output=True,timeout=10)


def run(root,version):
    require_guest()
    if version not in ('4.1','4.2'): raise ValueError('Explicit NFSv4 minor required')
    for name in ('rpc.mountd','nfsdcld','rpcbind'):
        if subprocess.run(['pgrep','-x',name],capture_output=True,timeout=5).returncode!=1:
            raise RuntimeError('Existing guest RPC/NFS actor blocks fixture')
    if command('exportfs','-v').strip(): raise RuntimeError('Existing guest exports block fixture')
    root=Path(root)
    if not root.is_absolute() or root.resolve()!=root: raise RuntimeError('Canonical new lab required')
    root.mkdir(mode=0o755)
    (root/'.disposable_nfs4').write_text('DISPOSABLE ONLY\n')
    data=root/'data';data.mkdir(mode=0o755)
    payload=data/'payload';payload.write_bytes(b'INITIAL\n');payload.chmod(0o666)
    (root/'mounted').mkdir()
    recovery=root/'recovery';recovery.mkdir()
    pipefs=root/'pipefs';pipefs.mkdir()
    namespace='mca-nfs4-'+uuid.uuid4().hex[:8]
    left='mcas'+uuid.uuid4().hex[:6];right='mcac'+uuid.uuid4().hex[:6]
    processes=[];logs=[];exported=False;namespace_created=False;link_created=False;server_owned=False;pipefs_mounted=False
    control=Path('/proc/fs/nfsd/threads')
    def spawn(args,name):
        log=(root/name).open('ab');logs.append(log)
        process=subprocess.Popen(args,stdout=log,stderr=log);processes.append(process);return process
    def wait_for(path,process,timeout=30):
        deadline=time.monotonic()+timeout
        while not path.exists():
            if process.poll() is not None: raise RuntimeError('Guest fixture process exited: '+str(process.returncode))
            if time.monotonic()>deadline: raise RuntimeError('Guest fixture checkpoint timeout: '+path.name)
            time.sleep(.1)
    try:
        # Module/control operations are confined to this VM's separate kernel.
        command('modprobe','nfsd');command('modprobe','nfsv4')
        if subprocess.run(['mountpoint','-q','/proc/fs/nfsd']).returncode:
            command('mount','-t','nfsd','nfsd','/proc/fs/nfsd')
        if control.read_text().strip()!='0': raise RuntimeError('Existing guest NFSD threads block fixture')
        server_owned=True
        command('mount','-t','rpc_pipefs','sunrpc',str(pipefs));pipefs_mounted=True
        command('ip','netns','add',namespace);namespace_created=True
        command('ip','link','add',left,'type','veth','peer','name',right);link_created=True
        command('ip','link','set',right,'netns',namespace)
        command('ip','addr','add','192.0.2.1/30','dev',left)
        command('ip','link','set',left,'up')
        command('ip','-n',namespace,'addr','add','192.0.2.2/30','dev',right)
        command('ip','-n',namespace,'link','set',right,'up')
        command('ip','-n',namespace,'link','set','lo','up')
        command('exportfs','-i','-o','rw,sync,no_subtree_check,all_squash,anonuid=65534,anongid=65534,insecure,fsid=0',
                '192.0.2.2:'+str(data));exported=True
        mountd=spawn(['rpc.mountd','-F','-N','2','-N','3','-p','20048'],'mountd.log')
        cld=spawn(['nfsdcld','-F','-p',str(pipefs),'-s',str(recovery)],'recovery.log')
        args=['rpc.nfsd','-H','192.0.2.1','-p','2049','-N','3','-V','4.1','-V','4.2','-G','10','-L','10','1']
        time.sleep(1)
        require_helpers_alive(mountd,cld)
        command(*args)
        require_helpers_alive(mountd,cld)
        versions=Path('/proc/fs/nfsd/versions').read_text().split()
        if '+2' in versions or '+3' in versions:
            raise RuntimeError('Unexpected legacy server version enabled')
        worker=spawn(['ip','netns','exec',namespace,'unshare','--mount','--propagation','private',
            sys.executable,'-B','-m','scripts.sqlite_nfs4_guest_lab','--client','--root',str(root),'--version',version],'client.log')
        wait_for(root/'client-ready',worker,40)
        require_helpers_alive(mountd,cld)
        if payload.read_bytes()!=b'BEFORE!\n': raise RuntimeError('Guest baseline bytes mismatch')
        tx_before=json.loads(command('ip','-n',namespace,'-s','-j','link','show','dev',right))[0]['stats64']['tx']['bytes']
        pause=spawn([sys.executable,'-c',
            'import time; from pathlib import Path; '
            'Path("/proc/fs/nfsd/threads").write_text("0\\n"); '
            'Path('+repr(str(root/'pause-ready'))+').touch(); time.sleep(60)'],'pause.log')
        wait_for(root/'pause-ready',pause)
        pause.kill();pause.wait(timeout=5)
        if control.read_text().strip()!='0': raise RuntimeError('Guest server not paused after controller death')
        (root/'write-request').touch()
        wait_for(root/'write-attempted',worker)
        time.sleep(3)
        tx_after=json.loads(command('ip','-n',namespace,'-s','-j','link','show','dev',right))[0]['stats64']['tx']['bytes']
        if (worker.poll() is not None or (root/'fsync-completed').exists()
                or payload.read_bytes()!=b'BEFORE!\n' or tx_after<=tx_before):
            raise RuntimeError('Guest paused-client uncertainty not established')
        write_returned=(root/'write-returned').exists()
        # Explicit recovery only, after independent server-byte observation.
        command(*args)
        wait_for(root/'fsync-completed',worker,60)
        wait_for(root/'client-unmounted',worker,20)
        worker.wait(timeout=5)
        if worker.returncode!=0 or payload.read_bytes()!=b'PENDING\n':
            raise RuntimeError('Guest recovery bytes/fsync mismatch')
        require_helpers_alive(mountd,cld)
        return {'recovery_helper_alive':True,'status':'private_guest_nfs4_recovery_complete','nfs_version':version,
                'kernel':os.uname().release,'paused_write_returned':write_returned,
                'paused_fsync_completed':False,'paused_server_bytes_unchanged':True,
                'client_network_tx_increased':True,'pause_controller_killed':True,
                'recovered_fsync_completed':True,'client_unmounted':True,
                'fixture_only':True,'production_authorized':False,'production_activation':'disabled',
                'writer_exclusion_verified':False,'restart_inhibition_verified':False}
    finally:
        if server_owned and control.exists():
            subprocess.run(['rpc.nfsd','0'],capture_output=True,timeout=15)
        for process in reversed(processes):
            if process.poll() is None:
                process.kill()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: pass
        if pipefs_mounted: subprocess.run(['umount',str(pipefs)],capture_output=True,timeout=10)
        if exported: subprocess.run(['exportfs','-u','192.0.2.2:'+str(data)],capture_output=True,timeout=10)
        if link_created: subprocess.run(['ip','link','del',left],capture_output=True,timeout=10)
        if namespace_created: subprocess.run(['ip','netns','del',namespace],capture_output=True,timeout=10)
        for log in logs: log.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True)
    parser.add_argument('--version',choices=('4.1','4.2'),required=True)
    parser.add_argument('--client',action='store_true')
    args=parser.parse_args()
    if args.client: client(args.root,args.version)
    else: print(json.dumps(run(args.root,args.version),sort_keys=True))
