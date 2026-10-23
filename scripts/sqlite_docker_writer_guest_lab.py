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


def run(root, binaries, image_archive, *, probe_runtime_route=False, integrate_copy=False):
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
        if probe_runtime_route:
            # Negative boundary experiment: only this fresh synthetic ID is
            # touched. Native containerd metadata is outside Docker HTTP AuthZ.
            if api('POST',route+'/update',{'Memory':67108864})[0]!=403:
                raise RuntimeError('Fixture HTTP comparison mutation not denied')
            runtime=[str(binaries/'ctr'),'--address',str(root/'exec/containerd/containerd.sock'),
                     '--namespace','moby','containers']
            changed=subprocess.run(runtime+['label',identity,'mca.disposable.native-route=observed'],
                env=env,capture_output=True,text=True,timeout=15)
            if changed.returncode:
                raise RuntimeError('Private native metadata experiment failed')
            observed=subprocess.run(runtime+['info',identity],env=env,capture_output=True,text=True,
                timeout=15,check=True)
            if json.loads(observed.stdout).get('Labels',{}).get('mca.disposable.native-route')!='observed':
                raise RuntimeError('Private native metadata change not observed')
            result['http_comparison_mutation_denied']=True
            result['native_runtime_metadata_mutation_observed']=True
            result['native_runtime_route_fenced']=False
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
        if integrate_copy:
            from scripts.sqlite_docker_copy_guest_lab import run_copy_case
            def observe_selected():
                if policy.poll() is not None:
                    raise RuntimeError('Guest selected-writer policy lost')
                status,body=api('GET','/info')
                if status!=200 or json.loads(body).get('Plugins',{}).get('Authorization')!=[plugin_name]:
                    raise RuntimeError('Guest engine policy binding unavailable')
                inspect_stopped()
            result['healthy_copy']=run_copy_case(root,observe_selected)
            def lose_policy():
                policy.kill();policy.wait(timeout=5)
            result['boundary_loss_copies']=[]
            for loss_at in ('publication','quarantine','completion','collection'):
                result['boundary_loss_copies'].append(run_copy_case(root,observe_selected,
                    lose_boundary=lose_policy,loss_at=loss_at))
                if loss_at!='collection':
                    policy=subprocess.Popen([sys.executable,'-B','-m',
                        'scripts.sqlite_docker_authorization_fixture','--root',str(control),
                        '--resume-fixture'],env=env,stdout=log,stderr=log)
                    processes.append(policy)
                    deadline=time.monotonic()+10
                    while True:
                        if policy.poll() is not None or time.monotonic()>deadline:
                            raise RuntimeError('Deny-only fixture policy reload failed')
                        try:
                            observe_selected()
                            break
                        except (OSError,RuntimeError,http.client.HTTPException):
                            time.sleep(.1)

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
    parser.add_argument('--probe-runtime-route',action='store_true',
                        help='Negative test: label only the new synthetic ID through private containerd')
    parser.add_argument('--integrate-copy',action='store_true',
                        help='Run synthetic bound copy and policy-loss retention cases')
    args=parser.parse_args()
    print(json.dumps(run(args.root,args.docker_bin,args.image_archive,probe_runtime_route=args.probe_runtime_route,integrate_copy=args.integrate_copy),sort_keys=True))
