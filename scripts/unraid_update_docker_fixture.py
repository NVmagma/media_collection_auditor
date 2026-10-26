"""Actual fixture-only swap/recovery, including a SIGKILL after durable stop.

All Docker operations are restricted to recorded IDs with fixture labels and
bind sources below this new private fixture volume. No production role is used.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys

from app.sqlite_preview_activation import validate_preview_activation, _revision
from app.sqlite_preview_install import _replace_config
from app.sqlite_release_recovery import _encode, _local
from app.sqlite_scheduled_paths import _open_directory
from app.state_store import GuardedSQLiteStateStore
from scripts.sqlite_preview_service import Docker, LABEL, verify_http_health
from scripts.unraid_update_transaction import apply_fixture_update, recover_fixture_update, UpdateJournal


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class FixtureEngine:
    def __init__(self, raw, context):
        self.raw, self.context, self.new = raw, context, None
        self.old, self.name = context['captured']['Id'], context['captured']['Name'][1:]
        self.roles = {self.name, self.name+'-rollback-'+self.old[:12]}

    def assert_fixture(self):
        if not re.fullmatch('auditor-fresh-fixture-[0-9a-f]{16}', self.name):
            raise RuntimeError('Recorded new fixture name required')
        if not re.fullmatch('/var/lib/docker/volumes/auditor-service-fixture-[0-9a-f]{16}/_data', self.context['host_root']):
            raise RuntimeError('Private newly created fixture volume required')
        self.check(self.old)

    def check(self, identity):
        if identity not in (self.old, self.new):
            raise RuntimeError('Container outside recorded fixture scope')
        value = self.raw.inspect(identity)
        label = '8'*64 if identity == self.old else self.context['attempt']
        if (value['Config'].get('Labels', {}).get(LABEL) != label or value['Image'] != self.context['image_id']
                or value['HostConfig'].get('PortBindings') or len(value['Mounts']) != 3
                or any(not Path(item['Source']).is_relative_to(self.context['host_root']) for item in value['Mounts'])):
            raise RuntimeError('Fixture identity, label, image or mounts changed')
        return value

    def inspect(self, value, optional=False):
        if value in (self.old, self.new): return self.check(value)
        if value not in self.roles: raise RuntimeError('Fixture role outside scope')
        result = self.raw.inspect(value, optional=optional)
        return None if result is None else self.check(result['Id'])

    def stop(self, value): self.check(value); self.raw.stop(value)
    def start(self, value): self.check(value); self.raw.start(value)

    def rename(self, value, role):
        self.check(value)
        if self.new: self.roles.add(self.name+'-replacement-retained-'+self.new[:12])
        if role not in self.roles: raise RuntimeError('Fixture rename outside scope')
        self.raw.rename(value, role)

    def create(self, role, payload):
        if role != self.name or self.new is not None or payload != self.context['payload']:
            raise RuntimeError('Exact single fixture replacement required')
        if any(not Path(item['Source']).is_relative_to(self.context['host_root']) for item in payload['HostConfig']['Mounts']):
            raise RuntimeError('Replacement fixture binds outside scope')
        self.new = self.raw.create(role, payload); self.check(self.new)
        return self.new

    def cleanup_new(self):
        if self.new:
            self.check(self.new)
            self.raw.request('DELETE', '/containers/'+self.new+'?force=1&v=0', statuses=(204,))


def validate_data(context):
    for env in (context['old_env'], context['new_env']):
        validate_preview_activation(settings=env)
        state, revision = GuardedSQLiteStateStore(env['SQLITE_STATE_FILE']).load_with_revision()
        if revision != 0 or digest(_encode(state)) != context['snapshot_sha256']:
            raise RuntimeError('Fixture tracking diverged')
        if digest(Path(env['WEB_CONFIG_FILE']).read_bytes()) != context['config_sha256']:
            raise RuntimeError('Fixture saved configuration changed')


def template(context, target):
    path = Path(context['template']); parent = _open_directory(str(path.parent))
    try:
        raw, info = _local(parent, path.name)
        desired = context[target].encode()
        if raw == desired: return
        if raw not in (context['old_template'].encode(), context['new_template'].encode()):
            raise RuntimeError('Private fixture template changed')
        _replace_config(parent, path.name, raw, info, desired)
    finally:
        os.close(parent)


def options(context, engine):
    return dict(engine=engine, captured=context['captured'], payload=context['payload'],
        image_id=context['image_id'], attempt=context['attempt'], validate_data=lambda: validate_data(context))


def run_rehearsal(*, raw, captured, image, old_env, new_env, destination):
    if _revision() != image['Config']['Labels']['org.opencontainers.image.revision']:
        raise RuntimeError('Matching actual fixture image required')
    host_root = os.environ['HOST_FIXTURE_ROOT']; destination = Path(destination)
    payload = deepcopy(captured['Config']); payload['Image'] = image['Id']
    runtime = dict(item.split('=',1) for item in image['Config'].get('Env', [])); runtime.update(new_env)
    payload['Env'] = [key+'='+value for key,value in sorted(runtime.items())]
    attempt = os.urandom(32).hex(); payload['Labels'] = {**payload.get('Labels', {}), LABEL: attempt}
    host = deepcopy(captured['HostConfig']); host['Binds'] = None; host['PortBindings'] = {}
    target_logs = str(Path(new_env['STATE_FILE']).parent)
    target_control = str(Path(new_env['SQLITE_STATE_FILE']).parent.parent)
    host['Mounts'] = [{'Type': 'bind', 'Source': str(Path(host_root)/Path(target).relative_to('/lab')),
                       'Target': target, 'ReadOnly': False, 'BindOptions': {'Propagation': 'rslave'}}
                      for target in (target_logs, target_control)]
    host['Mounts'].append({'Type':'bind', 'Source':str(Path(host_root)/'media'), 'Target':'/media',
                           'ReadOnly':True, 'BindOptions':{'Propagation':'rslave'}})
    payload['HostConfig'] = host
    context = dict(captured=captured, payload=payload, image_id=image['Id'], attempt=attempt,
        host_root=host_root, old_env=old_env, new_env=new_env, template=str(destination/'managed-template.xml'),
        old_template='<Container><Name>fixture-old</Name></Container>',
        new_template='<Container><Name>fixture-replacement</Name></Container>',
        snapshot_sha256=digest(_encode(GuardedSQLiteStateStore(old_env['SQLITE_STATE_FILE']).load_with_revision()[0])),
        config_sha256=digest(Path(old_env['WEB_CONFIG_FILE']).read_bytes()))
    Path(context['template']).write_text(context['old_template']); os.chmod(context['template'],0o600)
    engine = FixtureEngine(raw, context)
    journal_path = destination/'swap-journal'; journal_path.mkdir(mode=0o700)
    parent = _open_directory(str(journal_path))
    try:
        result = apply_fixture_update(**options(context, engine), journal=UpdateJournal(parent),
            health=lambda item: verify_http_health(engine=engine, identity=item['Id'], env=new_env),
            install_template=lambda: template(context,'new_template'))
        if result['status'] != 'fixture_update_complete': raise RuntimeError('Fixture swap incomplete')
        if raw.inspect(engine.old)['State']['Running']: raise RuntimeError('Old fixture automatically restored')
        recover_fixture_update(**options(context, engine), journal=UpdateJournal(parent,'recovery'), parent=parent,
            health=lambda item: verify_http_health(engine=engine, identity=item['Id'], env=old_env),
            restore_template=lambda: template(context,'old_template'))
        if Path(context['template']).read_text() != context['old_template']:
            raise RuntimeError('Private fixture template was not restored')
    finally:
        os.close(parent); engine.cleanup_new()
    # A new attempt/journal tests actual controller death after stopping the old
    # worker. The parent observes it stopped before explicitly requesting recovery.
    crash_path = destination/'crash-journal'; crash_path.mkdir(mode=0o700)
    context['journal'] = str(crash_path)
    context_path = destination/'crash-context.json'; context_path.write_bytes(_encode(context)); context_path.chmod(0o600)
    result = subprocess.run([sys.executable,'-B','-m','scripts.unraid_update_docker_fixture',str(context_path)],
                            capture_output=True, timeout=45)
    if result.returncode != -signal.SIGKILL: raise RuntimeError('Fixture controller was not killed at its boundary')
    if raw.inspect(context['captured']['Id'])['State']['Running']:
        raise RuntimeError('Stopped fixture automatically restarted after controller death')
    engine = FixtureEngine(raw, context); parent = _open_directory(str(crash_path))
    try:
        recover_fixture_update(**options(context,engine), journal=UpdateJournal(parent,'recovery'), parent=parent,
            health=lambda item: verify_http_health(engine=engine, identity=item['Id'], env=old_env),
            restore_template=lambda: template(context,'old_template'))
    finally:
        os.close(parent)
    validate_data(context)
    return {'status':'actual_fixture_swap_recovery_and_controller_death_verified', 'fixture_only':True,
            'automatic_restoration':False, 'production_authorized':False, 'host_ports_published':False,
            'actual_sigkill_verified':True, 'explicit_recovery_verified':True, 'controller_kill_boundary':'old_stopped'}


def child(path):
    path = Path(path)
    if not path.is_relative_to('/lab') or path.name != 'crash-context.json':
        raise RuntimeError('Private disposable crash context required')
    parent = _open_directory(str(path.parent))
    try: context = json.loads(_local(parent,path.name)[0])
    finally: os.close(parent)
    if context['host_root'] != os.environ['HOST_FIXTURE_ROOT']:
        raise RuntimeError('Fixture host root changed')
    raw = Docker(endpoint='/docker-engine.sock',expected_daemon=os.environ['EXPECTED_DAEMON_ID'])
    engine = FixtureEngine(raw,context); parent = _open_directory(context['journal'])
    class KillAfterStop(UpdateJournal):
        def event(self, phase, **values):
            super().event(phase, **values)
            if phase == 'old_stopped': os.kill(os.getpid(), signal.SIGKILL)
    try:
        apply_fixture_update(**options(context,engine), journal=KillAfterStop(parent),
            health=lambda item: None, install_template=lambda: None)
    finally: os.close(parent)


if __name__ == '__main__':
    child(sys.argv[1])
