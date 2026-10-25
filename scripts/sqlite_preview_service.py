"""Explicit preview service transaction, run only by the reviewed host launcher.

No work happens on import. The request journal records intent before every
external operation. Exceptions and lost acknowledgements stop the transaction;
there is no retry, automatic rollback, generic command execution or name adoption.
The approved original container is retained, never removed.
"""
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import stat
from time import monotonic, sleep
from urllib.parse import quote, urlencode

from app.sqlite_disposable_restore import _write_private
from app.sqlite_json import parse_unique_json
from app.sqlite_lock import _exclusive_lock
from app.sqlite_preview_install import (read_install_packet, stage_preview, restore_original_settings,
    _private_root, _replace_config)
from app.sqlite_preview_template import bind_published_reference
from app.sqlite_release_recovery import _encode, _local
from app.sqlite_scheduled_paths import _open_directory, scan_held_directory
from app.sqlite_state import validate_snapshot
from app.sqlite_operation_coordinator import INTENTS_KEY

REQUEST = 'service-request.json'
LABEL = 'io.media-collection-auditor.cutover-request'
NAME = 'media_collection_auditor'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def container_id(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise RuntimeError('Exact container ID required')
    return value


class UnixConnection(http.client.HTTPConnection):
    def __init__(self, endpoint):
        super().__init__('docker-host', timeout=45)
        self.endpoint = endpoint
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.endpoint)


class Docker:
    """Bound socket, versioned API, fixed methods; never retry an external request."""
    def __init__(self, *, endpoint, expected_daemon):
        self.endpoint = endpoint
        info = os.stat(endpoint, follow_symlinks=False)
        if not stat.S_ISSOCK(info.st_mode): raise RuntimeError('Docker socket required')
        self.socket_identity = info.st_dev, info.st_ino
        self.prefix = ''
        version = self.request('GET', '/version')
        api = version.get('ApiVersion')
        if not isinstance(api, str) or not re.fullmatch(r'1\.[0-9]{2}', api):
            raise RuntimeError('Supported Docker API version required')
        self.prefix = '/v' + api
        if self.request('GET', '/info').get('ID') != expected_daemon:
            raise RuntimeError('Selected Docker daemon changed')

    def check(self):
        info = os.stat(self.endpoint, follow_symlinks=False)
        if not stat.S_ISSOCK(info.st_mode) or (info.st_dev, info.st_ino) != self.socket_identity:
            raise RuntimeError('Docker socket binding changed')

    def request(self, method, route, payload=None, statuses=(200,)):
        self.check(); connection = UnixConnection(self.endpoint)
        try:
            body = None if payload is None else _encode(payload)
            connection.request(method, self.prefix + route, body=body,
                headers={} if body is None else {'Content-Type': 'application/json'})
            response = connection.getresponse(); raw = response.read(8 * 1024 * 1024 + 1)
            self.check()
            if response.status not in statuses or len(raw) > 8 * 1024 * 1024:
                raise RuntimeError('Docker operation acknowledgement unavailable')
            if response.status == 404: return None
            return parse_unique_json(raw) if raw else None
        finally:
            connection.close()

    def inspect(self, value, optional=False):
        return self.request('GET', '/containers/' + quote(value, safe='') + '/json',
                            statuses=(200, 404) if optional else (200,))

    def image(self, value):
        return self.request('GET', '/images/' + quote(value, safe='') + '/json')

    def stop(self, identity):
        self.request('POST', '/containers/' + container_id(identity) + '/stop?t=30', statuses=(204,))

    def rename(self, identity, name):
        self.request('POST', '/containers/' + container_id(identity) + '/rename?' + urlencode({'name': name}), statuses=(204,))

    def create(self, name, payload):
        value = self.request('POST', '/containers/create?' + urlencode({'name': name}), payload, statuses=(201,))
        return container_id(value.get('Id'))

    def start(self, identity):
        self.request('POST', '/containers/' + container_id(identity) + '/start', statuses=(204,))


class Journal:
    """Exclusive durable records; incomplete transactions are never continued."""
    def __init__(self, parent, prefix='service'):
        if prefix not in ('service', 'recovery'): raise ValueError('Known journal scope required')
        self.parent = parent
        self.prefix = prefix
        self.sequence = 0
        self.previous = '0' * 64

    def begin(self, request):
        _write_private(self.parent, self.prefix + '-request.json', _encode(request))
        self.previous = sha(_encode(request))

    def event(self, phase, **details):
        self.sequence += 1
        raw = _encode({'sequence': self.sequence, 'previous_sha256': self.previous, 'phase': phase, **details})
        _write_private(self.parent, f'{self.prefix}-{self.sequence:04d}.json', raw)
        self.previous = sha(raw)


def mount_records(value):
    # Docker inspection does not promise array order. Retain every field and
    # duplicate row, comparing complete canonical records rather than positions.
    if not isinstance(value, list): return None
    return tuple(sorted(_encode(item) for item in value))


def validate_original(live, captured, *, name, running):
    if (live.get('Id') != captured['Id'] or live.get('Image') != captured['Image']
            or live.get('Name') != '/' + name or live.get('State', {}).get('Running') is not running
            or any(live.get('State', {}).get(key) for key in ('Paused', 'Restarting', 'Dead'))
            or any(live.get(key) != captured.get(key) for key in ('Config', 'HostConfig'))
            or mount_records(live.get('Mounts')) != mount_records(captured.get('Mounts'))):
        raise RuntimeError('Original auditor changed since private review')


def preview_payload(*, captured, image, env, control_host, reference, request_id):
    """Translate only the reviewed ordinary bridge layout into Docker API data."""
    config = deepcopy(captured['Config']); host = deepcopy(captured['HostConfig'])
    runtime_env = dict(item.split('=', 1) for item in image['Config'].get('Env', []))
    runtime_env.update(env)
    if host['NetworkMode'] not in ('bridge', 'default'):
        raise RuntimeError('Initial service cutover requires reviewed bridge network')
    for key in ('Hostname', 'Domainname', 'MacAddress', 'Healthcheck'):
        if key == 'Hostname' and config.get(key) == captured['Id'][:12]: config.pop(key, None)
        if key in ('MacAddress', 'Healthcheck'): config.pop(key, None)
    config.update(Image=reference, User='0:0', WorkingDir='/app', Cmd=image['Config'].get('Cmd'),
        Entrypoint=image['Config']['Entrypoint'], StopSignal='SIGINT', Volumes=None,
        Env=[key + '=' + value for key, value in sorted(runtime_env.items())])
    labels = {key: value for key, value in config.get('Labels', {}).items()
              if not key.startswith(('org.opencontainers.image.', 'io.media-collection-auditor.'))}
    config['Labels'] = {**image['Config'].get('Labels', {}), **labels, LABEL: request_id}
    host.update(Binds=None, ReadonlyRootfs=True, AutoRemove=False,
        RestartPolicy={'Name': 'no', 'MaximumRetryCount': 0}, NetworkMode='bridge',
        Tmpfs={'/tmp': 'rw,noexec,nosuid,nodev,size=64m,mode=1777'})
    host['SecurityOpt'] = list(host.get('SecurityOpt') or [])
    if not any(value.startswith('no-new-privileges') for value in host['SecurityOpt']):
        host['SecurityOpt'].append('no-new-privileges')
    host['Mounts'] = [{'Type': 'bind', 'Source': mount['Source'], 'Target': mount['Destination'],
        'ReadOnly': mount['Destination'] == '/media',
        'BindOptions': {'Propagation': mount.get('Propagation', 'rprivate')}} for mount in captured['Mounts']]
    host['Mounts'].append({'Type': 'bind', 'Source': control_host, 'Target': '/sqlite-control', 'ReadOnly': False})
    config['HostConfig'] = host
    return config


def validate_preview(live, *, identity, image_id, request_id, payload, running):
    expected_mounts = {item['Target']: (item['Source'], not item['ReadOnly']) for item in payload['HostConfig']['Mounts']}
    actual_mounts = {item['Destination']: (item['Source'], item['RW']) for item in live.get('Mounts', [])}
    config, host, state = live.get('Config', {}), live.get('HostConfig', {}), live.get('State', {})
    expected_env = dict(item.split('=', 1) for item in payload['Env'])
    actual_env = dict(item.split('=', 1) for item in config.get('Env', []))
    if (type(running) is not bool or live.get('Id') != identity or live.get('Image') != image_id or live.get('Name') != '/' + NAME
            or state.get('Running') is not running or any(state.get(k) for k in ('Paused', 'Restarting', 'Dead'))
            or config.get('Labels', {}).get(LABEL) != request_id
            or actual_env != expected_env or len(config.get('Env', [])) != len(actual_env)
            or config.get('Entrypoint') != ['python', '-m', 'app.main'] or config.get('User') != '0:0'
            or config.get('WorkingDir') != '/app' or config.get('StopSignal') != 'SIGINT'
            or host.get('ReadonlyRootfs') is not True or host.get('RestartPolicy', {}).get('Name') != 'no'
            or host.get('Privileged') is not False or host.get('NetworkMode') != 'bridge'
            or host.get('PortBindings') != payload['HostConfig'].get('PortBindings')
            or actual_mounts != expected_mounts or len(live.get('Mounts', [])) != len(actual_mounts)):
        raise RuntimeError('Created preview differs from reviewed layout')


def apply_service(*, engine, journal, captured, report, env, reference, request_id,
                  stage, health, install_template, context=None):
    """One explicitly approved attempt. All callbacks are fixed offline operations.

    The original is always retained. Any exception, including transport timeout
    after a successful operation, propagates without retries or service recovery.
    """
    old_id = container_id(captured['Id'])
    container_id(request_id)
    if not re.fullmatch(r'ghcr\.io/nvmagma/media_collection_auditor@sha256:[0-9a-f]{64}', reference):
        raise RuntimeError('Approved immutable registry reference required')
    rollback_name = NAME + '_rollback_' + old_id[:12]
    image = engine.image(reference)
    if (image.get('Id') != report['preview_image_id'] or image.get('Config', {}).get('Volumes')
            or image.get('Config', {}).get('Entrypoint') != ['python', '-m', 'app.main']
            or image.get('Config', {}).get('StopSignal') != 'SIGINT'
            or image.get('Config', {}).get('Labels', {}).get('io.media-collection-auditor.sqlite-activation') != 'preview-only'
            or image.get('Config', {}).get('Labels', {}).get('org.opencontainers.image.revision') != report['source_revision']
            or reference not in (image.get('RepoDigests') or [])):
        raise RuntimeError('Published digest does not match the reviewed cached image')
    validate_original(engine.inspect(old_id), captured, name=NAME, running=True)
    if engine.inspect(rollback_name, optional=True) is not None:
        raise RuntimeError('Reserved rollback name is occupied')
    payload = preview_payload(captured=captured, image=image, env=env,
        control_host=report['control_host_path'], reference=reference, request_id=request_id)
    journal.begin({'schema_version': 1, 'request_id': request_id, 'original_container_id': old_id,
        'preview_image_id': report['preview_image_id'], 'reference': reference,
        'source_revision': report['source_revision'], 'automatic_restoration': False,
        'context': context or {}})
    journal.event('original_stop_requested')
    engine.stop(old_id)
    validate_original(engine.inspect(old_id), captured, name=NAME, running=False)
    journal.event('original_stopped')
    journal.event('offline_preparation_requested')
    stage()
    journal.event('offline_prepared')
    validate_original(engine.inspect(old_id), captured, name=NAME, running=False)
    journal.event('original_archive_requested')
    engine.rename(old_id, rollback_name)
    validate_original(engine.inspect(old_id), captured, name=rollback_name, running=False)
    journal.event('original_archived')
    if engine.inspect(NAME, optional=True) is not None:
        raise RuntimeError('Preview name was occupied during cutover')
    journal.event('preview_create_requested')
    new_id = engine.create(NAME, payload)
    journal.event('preview_created', container_id=new_id)
    validate_preview(engine.inspect(new_id), identity=new_id, image_id=report['preview_image_id'],
        request_id=request_id, payload=payload, running=False)
    journal.event('preview_start_requested', container_id=new_id)
    engine.start(new_id)
    validate_preview(engine.inspect(new_id), identity=new_id, image_id=report['preview_image_id'],
        request_id=request_id, payload=payload, running=True)
    journal.event('preview_started', container_id=new_id)
    health(engine.inspect(new_id))
    journal.event('preview_health_verified', container_id=new_id)
    validate_original(engine.inspect(old_id), captured, name=rollback_name, running=False)
    journal.event('managed_template_install_requested')
    install_template()
    journal.event('managed_template_installed')
    validate_preview(engine.inspect(new_id), identity=new_id, image_id=report['preview_image_id'],
        request_id=request_id, payload=payload, running=True)
    journal.event('cutover_complete', container_id=new_id)
    return {'status': 'preview_service_cutover_complete', 'preview_container_id': new_id,
        'original_container_retained': True, 'automatic_restoration': False, 'media_actions_authorized': False}


PHASES = ('original_stop_requested', 'original_stopped', 'offline_preparation_requested', 'offline_prepared',
    'original_archive_requested', 'original_archived', 'preview_create_requested', 'preview_created',
    'preview_start_requested', 'preview_started', 'preview_health_verified',
    'managed_template_install_requested', 'managed_template_installed', 'cutover_complete')


def read_service_history(parent):
    raw = _local(parent, REQUEST)[0]; request = parse_unique_json(raw)
    if type(request.get('schema_version')) is not int or request['schema_version'] != 1:
        raise RuntimeError('Service request schema invalid')
    previous, events, new_id = sha(raw), [], None
    # Reopen '.' relative to the pinned directory for an independent cursor.
    # listdir(fd) / dup(fd) can inherit an exhausted or filesystem-cached stream
    # and incorrectly report an empty journal on Tower's Docker storage.
    with scan_held_directory(parent) as entries:
        names = sorted(entry.name for entry in entries if re.fullmatch(r'service-[0-9]{4}\.json', entry.name))
    if len(names) > len(PHASES): raise RuntimeError('Unexpected service history length')
    for number, name in enumerate(names, 1):
        if name != f'service-{number:04d}.json': raise RuntimeError('Incomplete service history')
        raw = _local(parent, name)[0]; event = parse_unique_json(raw)
        if (type(event.get('sequence')) is not int or event.get('sequence') != number or event.get('previous_sha256') != previous
                or event.get('phase') != PHASES[number - 1]):
            raise RuntimeError('Service journal chain invalid')
        if event['phase'] == 'preview_created': new_id = container_id(event.get('container_id'))
        if 'container_id' in event and event['container_id'] != new_id:
            raise RuntimeError('Service journal container scope changed')
        events.append(event); previous = sha(raw)
    # A stale/truncated directory listing must not look like "no more effects".
    # Every effect has a contiguous durable intent record; verify the next slot
    # through an independent name lookup before accepting the observed prefix.
    try:
        os.stat(f'service-{len(names) + 1:04d}.json', dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        raise RuntimeError('Service history enumeration incomplete')
    return request, events, new_id


def recover_service(*, engine, journal, captured, report, env, reference, request_id,
                    events, recorded_new_id, restore_settings, restore_template, reviewed_new_id=None):
    """Explicit recovery only; prove identities and stop preview before restoring.

    A lost create acknowledgement requires a human-supplied exact preview ID;
    recovery never discovers/adopts a container by name. Changed/advanced state
    is refused by restore_settings and the original remains stopped.
    """
    old_id = container_id(captured['Id']); rollback_name = NAME + '_rollback_' + old_id[:12]
    new_id = recorded_new_id
    if reviewed_new_id is not None:
        reviewed_new_id = container_id(reviewed_new_id)
        if new_id is not None and new_id != reviewed_new_id:
            raise RuntimeError('Reviewed preview ID differs from journal')
        new_id = reviewed_new_id
    phases = [event['phase'] for event in events]
    if 'preview_create_requested' in phases and new_id is None:
        raise RuntimeError('Lost create acknowledgement requires explicit preview ID review')
    old = engine.inspect(old_id)
    if old.get('Name') not in ('/' + NAME, '/' + rollback_name):
        raise RuntimeError('Original rollback name changed')
    validate_original(old, captured, name=old['Name'][1:], running=False)
    image = engine.image(reference)
    if image.get('Id') != report['preview_image_id'] or reference not in (image.get('RepoDigests') or []):
        raise RuntimeError('Recovery image reference changed')
    payload = preview_payload(captured=captured, image=image, env=env,
        control_host=report['control_host_path'], reference=reference, request_id=request_id)
    preview = None
    if new_id is not None:
        preview = engine.inspect(new_id)
        validate_preview(preview, identity=new_id, image_id=report['preview_image_id'],
            request_id=request_id, payload=payload, running=preview.get('State', {}).get('Running'))
    journal.begin({'schema_version': 1, 'request_id': request_id, 'original_container_id': old_id,
        'preview_container_id': new_id, 'automatic_restoration': False})
    if preview is not None and preview['State']['Running']:
        journal.event('preview_stop_requested', container_id=new_id)
        engine.stop(new_id)
        validate_preview(engine.inspect(new_id), identity=new_id, image_id=report['preview_image_id'],
            request_id=request_id, payload=payload, running=False)
        journal.event('preview_stopped', container_id=new_id)
    journal.event('settings_restore_requested')
    restore_settings()
    journal.event('settings_restored')
    journal.event('managed_template_restore_requested')
    restore_template()
    journal.event('managed_template_restored')
    if new_id is not None:
        journal.event('preview_archive_requested', container_id=new_id)
        engine.rename(new_id, NAME + '_preview_retained_' + new_id[:12])
        journal.event('preview_archived', container_id=new_id)
    if old['Name'] != '/' + NAME:
        journal.event('original_name_restore_requested')
        engine.rename(old_id, NAME)
        journal.event('original_name_restored')
    validate_original(engine.inspect(old_id), captured, name=NAME, running=False)
    journal.event('original_start_requested')
    engine.start(old_id)
    validate_original(engine.inspect(old_id), captured, name=NAME, running=True)
    journal.event('recovery_complete')
    return {'status': 'original_auditor_recovered', 'original_container_id': old_id,
        'preview_container_retained': new_id is not None, 'automatic_restoration': False,
        'media_actions_authorized': False}


def verify_http_health(*, engine, identity, env):
    """Bounded read-only readiness probes. Never follow redirects or use proxies."""
    port = int(env.get('WEB_PORT', '8080')); token = env.get('INTEGRATION_API_TOKEN')
    if not token: raise RuntimeError('Existing integration token required')
    deadline = monotonic() + 30
    while monotonic() < deadline:
        current = engine.inspect(identity)
        if current.get('State', {}).get('Running') is not True:
            raise RuntimeError('Preview stopped before readiness')
        address = current.get('NetworkSettings', {}).get('Networks', {}).get('bridge', {}).get('IPAddress')
        try:
            parsed = ipaddress.ip_address(address)
            if parsed.version != 4 or not parsed.is_private or parsed.is_loopback or parsed.is_link_local:
                raise RuntimeError('Private bridge preview address required')
            def get(route, authenticated):
                connection = http.client.HTTPConnection(str(parsed), port, timeout=2)
                try:
                    connection.request('GET', route, headers={'Authorization': 'Bearer ' + token} if authenticated else {})
                    response = connection.getresponse(); raw = response.read(1024 * 1024 + 1)
                    if len(raw) > 1024 * 1024: raise RuntimeError('Bounded integration response required')
                    return response.status, parse_unique_json(raw)
                finally:
                    connection.close()
            for route in ('/api/v1/summary', '/api/v1/audit-status'):
                if get(route, False)[0] != 401: raise RuntimeError('API authentication boundary changed')
            code, summary = get('/api/v1/summary', True)
            status, audit = get('/api/v1/audit-status', True)
            if (code != 200 or status != 200 or summary.get('storage_authority') != 'sqlite'
                    or any(value.get('production_activation') != 'preview_only'
                           or value.get('freshness_verified') is not False or value.get('read_only') is not True
                           or value.get('media_actions_authorized') is not False
                           or value.get('execution_mode') != 'scheduled_preview' for value in (summary, audit))
                    or not audit.get('next_run')):
                raise RuntimeError('Preview API/coordinator not ready')
            return
        except (OSError, ValueError, RuntimeError):
            sleep(.25)
    raise RuntimeError('Preview readiness deadline expired')


def execute_approved(*, action, directory, packet_identity, control_identity, image_id,
                     reference, approved_review_sha, daemon_id, controller_revision,
                     reviewed_new_id=None, engine=None):
    """Concrete private binds, exact request approval and offline callbacks.

    Called only by an explicit approved host launcher. No publication occurs
    here; the engine must already resolve the immutable digest to the accepted ID.
    """
    if action not in ('apply', 'rollback'): raise ValueError('Explicit service action required')
    if not re.fullmatch('[0-9a-f]{40}', controller_revision): raise ValueError('Controller revision required')
    with ExitStack() as stack:
        packet = Path(directory)
        parent = _private_root(packet, packet_identity); stack.callback(os.close, parent)
        stack.enter_context(_exclusive_lock(Path(f'/proc/self/fd/{parent}') / '.service.lock', 'Service controller already active'))
        review_raw = _local(parent, 'review.json')[0]
        if sha(review_raw) != approved_review_sha: raise RuntimeError('Exact approved private review required')
        report, env, proposed = read_install_packet(directory=packet, expected_identity=packet_identity, preview_image=image_id)
        if not re.fullmatch('[A-Za-z0-9_-]{32,256}', env.get('INTEGRATION_API_TOKEN', '')):
            raise RuntimeError('Valid existing integration credential required before service changes')
        if (report.get('managed_template_plan') != 'prepared_not_installed' or report.get('network_mode') != 'bridge'
                or env.get('STATE_FILE') != '/app/logs/auditor_state.json'
                or env.get('WEB_CONFIG_FILE') != '/app/logs/auditor_config.json'
                or env.get('SQLITE_STATE_FILE') != '/sqlite-control/release/state.db'):
            raise RuntimeError('Complete reviewed initial service layout required')
        captured = parse_unique_json(_local(parent, 'original.inspect.json')[0])[0]
        original_xml = _local(parent, 'original-template.xml')[0]
        final_xml = bind_published_reference(proposed=_local(parent, 'proposed-template.xml')[0], reference=reference)
        control = _private_root(Path('/sqlite-control'), control_identity); stack.callback(os.close, control)
        if action == 'apply':
            with scan_held_directory(control) as entries:
                if next(entries, None) is not None:
                    raise RuntimeError('Fresh empty control root required before stopping any service')
        templates = _open_directory('/unraid-templates'); stack.callback(os.close, templates)
        template_name = 'my-media_collection_auditor.xml'
        current_xml, template_info = _local(templates, template_name)
        source = Path(env['STATE_FILE']); config = Path(env['WEB_CONFIG_FILE'])
        settings_parent = _open_directory(str(config.parent)); stack.callback(os.close, settings_parent)
        engine = engine or Docker(endpoint='/docker-engine.sock', expected_daemon=daemon_id)
        context = {'approved_review_sha256': approved_review_sha, 'daemon_id': daemon_id,
            'controller_revision': controller_revision, 'controller_sha256': sha(Path(__file__).read_bytes())}
        if action == 'apply':
            if current_xml != original_xml: raise RuntimeError('Managed template changed since capture')
            if sha(_local(settings_parent, config.name)[0]) != report['input_sha256']['original-config.json']:
                raise RuntimeError('Saved settings changed since capture')
            def stage():
                stage_preview(source=source, config=config, control_root=Path('/sqlite-control'),
                    expected_control_identity=control_identity,
                    expected_config_sha256=report['input_sha256']['original-config.json'],
                    proposed_config=proposed, settings=env)
            def install_template():
                _replace_config(templates, template_name, original_xml, template_info, final_xml)
            request_id = sha(_encode({**context, 'reference': reference, 'preview_image_id': image_id}))
            return apply_service(engine=engine, journal=Journal(parent), captured=captured, report=report,
                env=env, reference=reference, request_id=request_id, stage=stage,
                health=lambda current: verify_http_health(engine=engine, identity=current['Id'], env=env),
                install_template=install_template, context=context)
        request, events, new_id = read_service_history(parent)
        if (request.get('context', {}).get('approved_review_sha256') != approved_review_sha
                or request.get('context', {}).get('daemon_id') != daemon_id
                or request.get('reference') != reference or request.get('preview_image_id') != image_id
                or request.get('source_revision') != report['source_revision']
                or request.get('original_container_id') != captured['Id']):
            raise RuntimeError('Recovery scope differs from original approved transaction')
        if request.get('request_id') != sha(_encode({**request['context'], 'reference': reference, 'preview_image_id': image_id})):
            raise RuntimeError('Original service request binding changed')
        if current_xml not in (original_xml, final_xml): raise RuntimeError('Changed managed template requires private recovery review')
        def restore_settings():
            current = _local(settings_parent, config.name)[0]
            early = not any(event['phase'] == 'offline_prepared' for event in events) and new_id is None and reviewed_new_id is None
            if early and sha(current) == report['input_sha256']['original-config.json']:
                # Preparation never handed off to another worker. Original JSON
                # and original settings remain selected; retain partial SQL.
                src_parent = _open_directory(str(source.parent))
                try: snapshot = parse_unique_json(_local(src_parent, source.name)[0])
                finally: os.close(src_parent)
                validate_snapshot(snapshot)
                if INTENTS_KEY in snapshot: raise RuntimeError('Pending original tracking operation')
                return
            restore_original_settings(source=source, config=config, control_root=Path('/sqlite-control'),
                                      expected_control_identity=control_identity)
        def restore_template():
            if current_xml != original_xml:
                _replace_config(templates, template_name, current_xml, template_info, original_xml)
        return recover_service(engine=engine, journal=Journal(parent, 'recovery'), captured=captured,
            report=report, env=env, reference=reference, request_id=request['request_id'], events=events,
            recorded_new_id=new_id, reviewed_new_id=reviewed_new_id,
            restore_settings=restore_settings, restore_template=restore_template)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('action', choices=('apply', 'rollback'))
    for name in ('packet-directory', 'packet-identity', 'control-identity', 'image-id', 'published-reference',
                 'approved-review-sha256', 'daemon-id', 'controller-revision'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--reviewed-preview-container-id')
    args = parser.parse_args()
    try:
        def identity(value):
            if not re.fullmatch('[0-9]+:[0-9]+', value): raise ValueError('Device:inode required')
            return tuple(int(part) for part in value.split(':'))
        report = execute_approved(action=args.action, directory=args.packet_directory,
            packet_identity=identity(args.packet_identity), control_identity=identity(args.control_identity),
            image_id=args.image_id, reference=args.published_reference, approved_review_sha=args.approved_review_sha256,
            daemon_id=args.daemon_id, controller_revision=args.controller_revision,
            reviewed_new_id=args.reviewed_preview_container_id)
    except Exception as error:
        print(json.dumps({'status': 'service_transaction_review_required', 'failure_category': type(error).__name__,
            'automatic_restoration': False, 'media_actions_authorized': False}))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
