"""Run only inside the new mca-writer-fixture Linux guest, never Tower.

Starts its OWN daemon and writer. No existing daemon/service is controlled.
Requires a fresh root, NoCloud fixture identity and no pre-existing dockerd.
"""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time
import uuid

from app.sqlite_docker_writer_observation import require_stopped_writer


class Client(http.client.HTTPConnection):
    def __init__(self, endpoint):
        super().__init__('private',timeout=35)
        self.endpoint=endpoint
    def connect(self):
        self.sock=socket.socket(socket.AF_UNIX)
        self.sock.settimeout(35)
        self.sock.connect(str(self.endpoint))


def run(root, binaries, image_archive):
    if (sys.platform!='linux' or os.geteuid()!=0
            or socket.gethostname()!='mca-writer-fixture'
            or Path('/var/lib/cloud/data/instance-id').read_text().strip()!='mca-writer-fixture'):
        raise RuntimeError('Dedicated disposable Linux guest required; never run on Tower')
    if subprocess.run(['pgrep','-x','dockerd'],capture_output=True,timeout=5).returncode!=1:
        raise RuntimeError('Existing daemon or ambiguous inventory blocks fixture')
    root=Path(root)
    binaries=Path(binaries)
    if not root.is_absolute() or root.resolve()!=root or not binaries.is_absolute():
        raise RuntimeError('Canonical new fixture paths required')
    root.mkdir(mode=0o700)
    (root/'.disposable_writer').write_text('DISPOSABLE ONLY\n')
    media=root/'media'; media.mkdir()
    config=root/'daemon.json'; config.write_text('{}\n')
    endpoint=root/'engine.sock'
    env={**os.environ,'PATH':str(binaries)+':/usr/sbin:/usr/bin:/sbin:/bin'}
    processes=[]
    logs=[]
    plugin_spec=None
    def start_daemon():
        log=(root/'daemon.log').open('ab'); logs.append(log)
        process=subprocess.Popen([str(binaries/'dockerd'), '--host','unix://'+str(endpoint),
            '--config-file',str(config),'--data-root',str(root/'data'),
            '--exec-root',str(root/'exec'),'--pidfile',str(root/'daemon.pid'),
            '--storage-driver','vfs','--bridge','none','--iptables=false',
            '--ip6tables=false','--ip-forward=false','--ip-masq=false'],
            env=env,stdout=log,stderr=log)
        processes.append(process)
        return process
    def api(method,route,value=None):
        client=Client(endpoint)
        try:
            body=None if value is None else json.dumps(value).encode()
            client.request(method,route,body=body,headers={} if body is None else {'Content-Type':'application/json'})
            response=client.getresponse(); data=response.read(1024*1024+1)
            if len(data)>1024*1024: raise RuntimeError('Fixture response exceeds bound')
            return response.status,data
        finally: client.close()
    def ready(process):
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            if process.poll() is not None: raise RuntimeError('Guest fixture daemon exited during startup')
            try:
                if api('GET','/_ping')[0]==200: return
            except (OSError,http.client.HTTPException): pass
            time.sleep(.2)
        raise RuntimeError('Guest daemon readiness timeout')
    def stop(process):
        if process.poll() is None:
            process.terminate()
            try: process.wait(timeout=20)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
    result={'fixture_only':True,'production_authorized':False,'production_activation':'disabled',
            'writer_exclusion_verified':False,'restart_inhibition_verified':False,
            'automatic_restoration':False}
    try:
        daemon=start_daemon(); ready(daemon)
        subprocess.run([str(binaries/'docker'),'--host','unix://'+str(endpoint),
            'image','load','--input',str(image_archive)],env=env,check=True,
            stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=60)
        status,data=api('POST','/containers/create',{'Image':'docker:29.8.2-dind',
            'Entrypoint':['sh','-c'], 'Cmd':["trap 'exit 0' TERM; while :; do echo tick >> /media/ticks; sleep 0.25; done"],
            'HostConfig':{'NetworkMode':'none','RestartPolicy':{'Name':'always','MaximumRetryCount':0},
                          'Binds':[str(media)+':/media:rw']}})
        if status!=201: raise RuntimeError('Guest writer creation failed: '+str(status))
        identity=json.loads(data)['Id']
        if not re.fullmatch(r'[0-9a-f]{64}',identity): raise RuntimeError('Invalid guest writer ID')
        route='/containers/'+identity
        if api('POST',route+'/start')[0]!=204: raise RuntimeError('Guest writer start failed')
        time.sleep(11)  # Real restart-policy monitoring baseline, not a stub.
        ticks=media/'ticks'
        before=ticks.read_bytes(); time.sleep(1)
        if len(ticks.read_bytes())<=len(before): raise RuntimeError('Guest writer not writing')
        result['baseline_writer_observed']=True
        control=root/'control'
        log=(root/'policy.log').open('ab'); logs.append(log)
        policy=subprocess.Popen([sys.executable,'-B','-m','scripts.sqlite_docker_authorization_fixture',
            '--root',str(control),'--quiesce-container-id',identity],env=env,stdout=log,stderr=log)
        processes.append(policy)
        deadline=time.monotonic()+10
        while not (control/'authorization.sock').is_socket():
            if policy.poll() is not None or time.monotonic()>deadline: raise RuntimeError('Guest plugin startup failed')
            time.sleep(.1)
        plugin_dir=Path('/etc/docker/plugins'); plugin_dir.mkdir(parents=True,exist_ok=True)
        plugin_name='mca-writer-'+uuid.uuid4().hex
        candidate=plugin_dir/(plugin_name+'.spec')
        with candidate.open('x') as spec:
            plugin_spec=candidate
            spec.write('unix://'+str(control/'authorization.sock'))
        config.write_text(json.dumps({'authorization-plugins':[plugin_name]}))
        os.kill(daemon.pid,signal.SIGHUP)
        deadline=time.monotonic()+10
        while api('POST',route+'/start')[0]!=403:
            if time.monotonic()>deadline: raise RuntimeError('Guest plugin reload not verified')
            time.sleep(.1)
        result['start_denial_verified']=True
        status,_=api('POST',route+'/update',{'RestartPolicy':{'Name':'no','MaximumRetryCount':0}})
        if status!=200: raise RuntimeError('Guest restart disable failed: '+str(status))
        if api('POST',route+'/stop')[0]!=204: raise RuntimeError('Guest writer stop failed')
        def inspect_stopped():
            status,body=api('GET',route+'/json')
            if status!=200: raise RuntimeError('Guest writer state unavailable: '+str(status))
            state=json.loads(body)
            require_stopped_writer(state,identity)
        inspect_stopped()
        digest=hashlib.sha256(ticks.read_bytes()).hexdigest()
        time.sleep(2)
        if hashlib.sha256(ticks.read_bytes()).hexdigest()!=digest: raise RuntimeError('Guest writer bytes changed')
        result['restart_disabled_and_stopped_verified']=True
        stop(daemon)
        daemon=start_daemon(); ready(daemon)
        inspect_stopped()
        if api('POST',route+'/start')[0]!=403: raise RuntimeError('Guest start denial lost after daemon restart')
        time.sleep(2)
        if hashlib.sha256(ticks.read_bytes()).hexdigest()!=digest: raise RuntimeError('Guest writer resumed after restart')
        result.update(status='private_guest_writer_quiescence_complete',
                      stopped_after_daemon_restart=True, fixture_bytes_unchanged=True)
        return result
    finally:
        for process in reversed(processes): stop(process)
        for log in logs: log.close()
        if plugin_spec is not None: plugin_spec.unlink()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True)
    parser.add_argument('--docker-bin',required=True)
    parser.add_argument('--image-archive',required=True)
    args=parser.parse_args()
    print(json.dumps(run(args.root,args.docker_bin,args.image_archive),sort_keys=True))
