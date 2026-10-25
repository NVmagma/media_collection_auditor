"""Private, offline review packet. No Docker/service commands are executed.

Input snapshots and generated environment/settings files contain credentials and
must stay private. The output summary contains only reviewed metadata/counts.
This does not migrate live state, verify quiescence, or authorize deployment.
"""
from contextlib import ExitStack
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import stat

from app.sqlite_disposable_restore import _write_private
from app.sqlite_json import parse_unique_json
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_preview_activation import _policy, _revision
from app.sqlite_release_recovery import _encode, _local
from app.sqlite_scheduled_paths import _canonical, _open_directory
from app.sqlite_state import SECTIONS, validate_snapshot

INPUTS = ('original.inspect.json', 'original-config.json', 'source-observed.json',
          'config-metadata.json', 'source-metadata.json')
ENV_FILE = 'preview.env'
CONFIG_FILE = 'proposed-config.json'
SPEC_FILE = 'container-plan.json'
REPORT_FILE = 'review.json'
ENV_MARKER = '@PRIVATE_PACKET_ENV_FILE@'


class ReviewBlocked(RuntimeError):
    pass


def _block(reason):
    raise ReviewBlocked(reason)


def _text(value):
    if not isinstance(value, str) or any(ord(c) < 32 or ord(c) == 127 for c in value):
        _block('unsupported_text_value')
    return value


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch('sha256:[0-9a-f]{64}', value):
        _block('immutable_image_id_required')
    return value


def _path(value):
    result = _canonical(value)
    if ',' in result: _block('unsupported_mount_path')
    return result


def _environment(items):
    if not isinstance(items, list): _block('container_environment_unavailable')
    values = {}
    for item in items:
        item = _text(item)
        key, separator, value = item.partition('=')
        if (not separator or not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', key)
                or key in values or len(item.encode('utf-8')) > 65535):
            _block('unsupported_container_environment')
        values[key] = value
    if any(values.get(key) for key in ('PYTHONHOME', 'PYTHONSTARTUP', 'LD_PRELOAD', 'LD_LIBRARY_PATH')):
        _block('custom_runtime_environment_requires_review')
    if values.get('AUDITOR_STATE_BACKEND', 'json') != 'json': _block('original_json_backend_required')
    return values


def _ports(host, web_port):
    result, public = [], []
    bindings = host.get('PortBindings') or {}
    if not isinstance(bindings, dict): _block('unsupported_port_bindings')
    for target, rows in sorted(bindings.items()):
        if not re.fullmatch('[0-9]{1,5}/(?:tcp|udp)', target) or not 1 <= int(target.split('/')[0]) <= 65535:
            _block('unsupported_port_bindings')
        if not isinstance(rows, list) or not rows: _block('explicit_published_ports_required')
        for row in rows:
            port, address = row.get('HostPort'), row.get('HostIp', '')
            if not isinstance(port, str) or not port.isascii() or not port.isdecimal() or not 1 <= int(port) <= 65535:
                _block('explicit_published_ports_required')
            if address:
                ipaddress.ip_address(address)
                shown = '[' + address + ']' if ':' in address else address
                value = shown + ':' + port + ':' + target
            else: value = port + ':' + target
            result.append('--publish=' + value)
            public.append({'container': target, 'host_ip': address, 'host_port': port})
    if str(web_port) + '/tcp' not in bindings:
        _block('stable_published_api_port_required')
    return result, public


def render_plan(*, original, saved, source, preview_image, rollback_image, control_host, source_revision):
    from app.config_store import KEYS, DEFAULTS
    from app.sqlite_run_schedule import DailyRunSchedule
    _sha(preview_image); _sha(rollback_image); control_host = _path(control_host)
    if not isinstance(source_revision, str) or not re.fullmatch('[0-9a-f]{40}', source_revision):
        _block('exact_preview_source_required')
    if not isinstance(original, list) or len(original) != 1 or not isinstance(original[0], dict):
        _block('single_original_container_required')
    old = original[0]
    name, identifier = old.get('Name'), old.get('Id')
    if name != '/media_collection_auditor' or not isinstance(identifier, str) or not re.fullmatch('[0-9a-f]{64}', identifier):
        _block('unexpected_original_container')
    if old.get('Image') != rollback_image or old.get('State', {}).get('Running') is not True:
        _block('running_expected_original_required')
    config, host = old.get('Config'), old.get('HostConfig')
    if not isinstance(config, dict) or not isinstance(host, dict): _block('container_configuration_unavailable')
    reference = config.get('Image')
    if not isinstance(reference, str) or not re.fullmatch(r'[A-Za-z0-9./_:-]+@sha256:[0-9a-f]{64}', reference):
        _block('immutable_original_reference_required')
    if config.get('User', '') not in ('', '0', '0:0', 'root', 'root:root'):
        _block('reviewed_root_identity_required')
    if config.get('Entrypoint') not in (['python', 'main.py'], ['python', '-m', 'app.main']):
        _block('custom_entrypoint_requires_review')
    if config.get('Cmd') not in (None, [], ['python3']) or config.get('WorkingDir', '/app') != '/app':
        _block('custom_command_requires_review')
    if config.get('Healthcheck'): _block('custom_healthcheck_requires_review')
    if host.get('Privileged') is not False or host.get('RestartPolicy', {}).get('Name') != 'no':
        _block('unexpected_privilege_or_restart_policy')
    if host.get('AutoRemove') or host.get('PublishAllPorts') or host.get('OomKillDisable'):
        _block('unsupported_automatic_container_control')
    for key in ('Devices', 'DeviceRequests', 'VolumesFrom', 'Links', 'Tmpfs', 'Sysctls',
            'Ulimits', 'LxcConf', 'DeviceCgroupRules', 'StorageOpt', 'Init', 'GroupAdd'):
        if host.get(key): _block('unsupported_host_configuration:' + key)
    for key in ('PidMode', 'UTSMode', 'UsernsMode'):
        if host.get(key) not in ('', None, 'private'): _block('unsupported_namespace:' + key)
    if host.get('IpcMode') not in ('', None, 'private'): _block('unsupported_namespace:IpcMode')
    if host.get('Runtime') not in ('', None, 'runc'): _block('custom_runtime_requires_review')
    for key in ('BlkioWeight', 'BlkioWeightDevice', 'BlkioDeviceReadBps', 'BlkioDeviceWriteBps',
                'BlkioDeviceReadIOps', 'BlkioDeviceWriteIOps', 'CpuRealtimePeriod', 'CpuRealtimeRuntime'):
        if host.get(key): _block('unsupported_resource_configuration:' + key)
    network = host.get('NetworkMode')
    if network not in ('bridge', 'default', 'host'): _block('custom_network_requires_review')
    env = _environment(config.get('Env'))
    if env.get('STATE_FILE', '/app/logs/auditor_state.json') != '/app/logs/auditor_state.json':
        _block('custom_state_path_requires_review')
    if env.get('WEB_CONFIG_FILE', '/app/logs/auditor_config.json') != '/app/logs/auditor_config.json':
        _block('custom_saved_config_path_requires_review')
    if not isinstance(saved, dict): _block('saved_configuration_invalid')
    effective = {**{k: DEFAULTS.get(k, '') for k in KEYS}, **env,
                 **{k: str(v) for k, v in saved.items() if k in KEYS}}
    if effective.get('DRY_RUN', 'true').strip().lower() != 'true': _block('original_dry_run_policy_changed')
    for key in ('ALLOW_PERMANENT_DELETE', 'ALLOW_FILESYSTEM_DELETE', 'ALLOW_CROSS_FILESYSTEM_MOVES', 'ENABLE_SEASON_PRUNING'):
        if effective.get(key, 'false').strip().lower() != 'false': _block('original_safety_policy_changed')
    validate_snapshot(source)
    if INTENTS_KEY in source: _block('source_pending_operation_requires_review')
    _encode(saved); _encode(source)
    schedule = {'SQLITE_DAILY_RUN_TIME': '02:00', 'SQLITE_DAILY_RUN_TIMEZONE': 'America/Los_Angeles'}
    DailyRunSchedule(schedule['SQLITE_DAILY_RUN_TIME'], schedule['SQLITE_DAILY_RUN_TIMEZONE'])
    safe = {key: 'false' for key in ('ALLOW_PERMANENT_DELETE', 'ALLOW_FILESYSTEM_DELETE',
                                   'ALLOW_CROSS_FILESYSTEM_MOVES', 'ENABLE_SEASON_PRUNING')}
    safe['DRY_RUN'] = 'true'
    proposed_config = dict(saved, **schedule, **safe)
    # Use the new image's interpreter/runtime defaults, preserving application env.
    for key in ('PATH', 'PYTHON_VERSION', 'PYTHON_SHA256', 'PYTHON_GET_PIP_URL', 'PYTHON_GET_PIP_SHA256',
                'PYTHON_PIP_VERSION', 'PYTHON_SETUPTOOLS_VERSION'):
        env.pop(key, None)
    env.update(schedule); env.update(safe)
    env.update(AUDITOR_STATE_BACKEND='sqlite', SQLITE_STATE_FILE='/sqlite-control/release/state.db',
        STATE_FILE='/app/logs/auditor_state.json', WEB_CONFIG_FILE='/app/logs/auditor_config.json',
        READ_ONLY_API_SERVICE='false', PYTHONPATH='/app/app:/app', PYTHONDONTWRITEBYTECODE='1', PYTHONUNBUFFERED='1')
    planned = {**env, **{k: str(v) for k, v in proposed_config.items() if k in KEYS}}
    for key in KEYS: planned.setdefault(key, DEFAULTS.get(key, ''))
    worker, _, _, _ = _policy(planned)  # Construction validates policy/transport; no HTTP.
    if any(not Path(path).is_relative_to('/media') for lib in worker.libraries for _, path in lib.roots):
        _block('custom_media_layout_requires_review')
    mounts = old.get('Mounts')
    if not isinstance(mounts, list) or len(mounts) != 2 or {m.get('Destination') for m in mounts} != {'/media', '/app/logs'}:
        _block('unexpected_original_mounts')
    args = ['create', '--pull=never', '--name=media_collection_auditor', '--user=0:0',
        '--restart=no', '--read-only', '--env-file=' + ENV_MARKER,
        '--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777',
        '--network=' + ('bridge' if network == 'default' else network)]
    for key, flag in (('Hostname', '--hostname='), ('Domainname', '--domainname=')):
        value = config.get(key)
        if value and value != identifier[:12]:
            if not re.fullmatch('[A-Za-z0-9_.-]{1,253}', value): _block('unsupported_hostname')
            args.append(flag + value)
    sources = []
    for mount in sorted(mounts, key=lambda item: item['Destination']):
        if mount.get('Type') != 'bind' or mount.get('RW') is not True: _block('unexpected_original_mount_mode')
        origin, target = _path(mount.get('Source')), mount['Destination']
        sources.append(Path(origin))
        if mount.get('Propagation', 'rprivate') not in ('rprivate', 'rslave'): _block('unsupported_bind_propagation')
        spec = 'type=bind,src=' + origin + ',dst=' + target + ',bind-propagation=' + mount.get('Propagation', 'rprivate')
        if target == '/media': spec += ',readonly'
        args.append('--mount=' + spec)
    if any(Path(control_host) == p or Path(control_host) in p.parents or p in Path(control_host).parents for p in sources):
        _block('control_host_overlaps_original_mount')
    args.append('--mount=type=bind,src=' + control_host + ',dst=/sqlite-control')
    web_port = env.get('WEB_PORT', '8080')
    if not isinstance(web_port, str) or not web_port.isascii() or not web_port.isdecimal() or not 1 <= int(web_port) <= 65535:
        _block('invalid_web_port')
    published, public_ports = _ports(host, web_port) if network != 'host' else ([], [])
    args.extend(published)
    for key, flag in (('Memory', '--memory'), ('MemorySwap', '--memory-swap'), ('MemoryReservation', '--memory-reservation'),
            ('PidsLimit', '--pids-limit'), ('CpuShares', '--cpu-shares'), ('CpuPeriod', '--cpu-period'), ('CpuQuota', '--cpu-quota')):
        value = host.get(key)
        if value not in (None, 0):
            if type(value) is not int or value < -1: _block('unsupported_resource_limit')
            args.append(flag + '=' + str(value))
    if host.get('NanoCpus'):
        from decimal import Decimal
        value = host['NanoCpus']
        if type(value) is not int or value < 0: _block('unsupported_resource_limit')
        args.append('--cpus=' + str(Decimal(value) / Decimal(1000000000)))
    if host.get('CpusetCpus'):
        value = _text(host['CpusetCpus'])
        if not re.fullmatch('[0-9,-]+', value): _block('unsupported_cpu_set')
        args.append('--cpuset-cpus=' + value)
    swappiness = host.get('MemorySwappiness')
    if swappiness is not None:
        if type(swappiness) is not int or not 0 <= swappiness <= 100: _block('unsupported_memory_swappiness')
        args.append('--memory-swappiness=' + str(swappiness))
    if host.get('CgroupnsMode'):
        if host['CgroupnsMode'] not in ('private', 'host'): _block('unsupported_cgroup_namespace')
        args.append('--cgroupns=' + host['CgroupnsMode'])
    for key in ('CapAdd', 'CapDrop'):
        for value in host.get(key) or []:
            if not re.fullmatch('[A-Za-z0-9_]+', value): _block('invalid_capability')
            args.append(('--cap-add=' if key == 'CapAdd' else '--cap-drop=') + value)
    for value in host.get('SecurityOpt') or []:
        if value not in ('no-new-privileges', 'no-new-privileges:true', 'label=disable'):
            _block('custom_security_option_requires_review')
        args.append('--security-opt=' + value)
    if not any(arg.startswith('--security-opt=no-new-privileges') for arg in args): args.append('--security-opt=no-new-privileges')
    for key, flag in (('Dns', '--dns='), ('DnsOptions', '--dns-option='), ('DnsSearch', '--dns-search='), ('ExtraHosts', '--add-host=')):
        for value in host.get(key) or []: args.append(flag + _text(value))
    logging = host.get('LogConfig') or {}
    if logging.get('Type'):
        if not re.fullmatch('[a-z0-9_-]+', logging['Type']): _block('unsupported_log_driver')
        args.append('--log-driver=' + logging['Type'])
        for key, value in sorted((logging.get('Config') or {}).items()): args.append('--log-opt=' + _text(key) + '=' + _text(value))
    labels = config.get('Labels') or {}
    for key, value in sorted(labels.items()):
        if not key.startswith(('org.opencontainers.image.', 'io.media-collection-auditor.')):
            args.append('--label=' + _text(key) + '=' + _text(value))
    args.append(preview_image)
    plan = {'schema_version': 1, 'source_revision': source_revision, 'original_container_id': identifier,
        'original_image_id': rollback_image, 'preview_image_id': preview_image, 'create_argv_template': args,
        'stop_original_argv': ['stop', '--time', '30', identifier],
        'archive_original_argv': ['rename', identifier, 'media_collection_auditor_rollback_' + identifier[:12]],
        'start_preview_argv': ['start', '@NEW_CONTAINER_ID@'],
        'stop_preview_argv': ['stop', '--time', '30', '@NEW_CONTAINER_ID@'],
        'remove_preview_argv': ['rm', '@NEW_CONTAINER_ID@'],
        'restore_original_name_argv': ['rename', identifier, 'media_collection_auditor'],
        'start_original_argv': ['start', identifier], 'deployment_authorized': False}
    report = {'status': 'cutover_review_prepared', 'source_revision': source_revision,
        'container_name': 'media_collection_auditor', 'original_container_id': identifier,
        'original_image_id': rollback_image, 'preview_image_id': preview_image,
        'network_mode': network, 'published_ports': public_ports, 'environment_entries': len(env),
        'control_host_path': control_host, 'sqlite_state_file': env['SQLITE_STATE_FILE'],
        'daily_time': schedule['SQLITE_DAILY_RUN_TIME'], 'timezone': schedule['SQLITE_DAILY_RUN_TIMEZONE'],
        'enabled_libraries': [lib.name for lib in worker.libraries], 'maximum_proposed_actions': worker.maximum_actions,
        'tracking_counts': {section: len(source[section]) for section in SECTIONS},
        'media_read_only': True, 'root_filesystem_read_only': True, 'execution_mode': 'scheduled_preview',
        'writer_quiescence_verified': False, 'deployment_authorized': False, 'service_actions_performed': False}
    return report, plan, env, proposed_config


def write_review_packet(*, directory, preview_image, rollback_image, control_host, source_revision):
    directory = Path(_canonical(str(directory)))
    with ExitStack() as stack:
        parent = _open_directory(str(directory)); stack.callback(os.close, parent)
        info = os.fstat(parent)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            _block('new_private_packet_directory_required')
        captured = {name: _local(parent, name) for name in INPUTS}
        template_status = 'not_captured'
        try:
            template = _local(parent, 'original-template.xml')
        except FileNotFoundError:
            pass
        else:
            from xml.etree import ElementTree
            if b'<!DOCTYPE' in template[0].upper() or b'<!ENTITY' in template[0].upper():
                _block('unsupported_template_declaration')
            parsed = ElementTree.fromstring(template[0])
            if parsed.findtext('Name') != 'media_collection_auditor':
                _block('unexpected_managed_template')
            captured['original-template.xml'] = template
            template_status = 'captured_for_review'
        for raw_name, meta_name, kind in (('original-config.json', 'config-metadata.json', 'config'),
                ('source-observed.json', 'source-metadata.json', 'state')):
            meta = parse_unique_json(captured[meta_name][0])
            if (meta.get('kind') != kind or meta.get('sha256') != hashlib.sha256(captured[raw_name][0]).hexdigest()
                    or meta.get('path') != ('/app/logs/auditor_config.json' if kind == 'config' else '/app/logs/auditor_state.json')
                    or type(meta.get('bytes')) is not int or meta['bytes'] != len(captured[raw_name][0])
                    or type(meta.get('process_uid')) is not int or meta['process_uid'] != 0
                    or type(meta.get('uid')) is not int or meta['uid'] != 0 or meta.get('quiescent') is not False):
                _block('captured_input_binding_mismatch')
        report, plan, env, proposed = render_plan(original=parse_unique_json(captured[INPUTS[0]][0]),
            saved=parse_unique_json(captured[INPUTS[1]][0]), source=parse_unique_json(captured[INPUTS[2]][0]),
            preview_image=preview_image, rollback_image=rollback_image, control_host=control_host, source_revision=source_revision)
        inputs_sha = {name: hashlib.sha256(raw).hexdigest() for name, (raw, _) in captured.items()}
        report.update(input_sha256=inputs_sha, original_settings_preserved=True, managed_template=template_status)
        plan['input_sha256'] = inputs_sha
        # The fixed output set is exclusive; a partial or completed packet is never reused.
        for name in (ENV_FILE, CONFIG_FILE, SPEC_FILE, REPORT_FILE):
            try: os.stat(name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError: continue
            _block('existing_packet_output')
        _write_private(parent, ENV_FILE, ''.join(key + '=' + value + '\n' for key, value in sorted(env.items())).encode('utf-8'))
        _write_private(parent, CONFIG_FILE, _encode(proposed))
        _write_private(parent, SPEC_FILE, _encode(plan))
        for name, (raw, original_info) in captured.items():
            current, current_info = _local(parent, name)
            if current != raw or current_info.st_ino != original_info.st_ino or current_info.st_dev != original_info.st_dev:
                _block('packet_input_changed')
        _write_private(parent, REPORT_FILE, _encode(report))
        return report


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--packet-directory', required=True)
    parser.add_argument('--preview-image', required=True)
    parser.add_argument('--rollback-image', required=True)
    parser.add_argument('--control-host-path', required=True)
    args = parser.parse_args()
    try:
        report = write_review_packet(directory=args.packet_directory, preview_image=args.preview_image,
            rollback_image=args.rollback_image, control_host=args.control_host_path, source_revision=_revision())
    except Exception as error:
        print(json.dumps({'status': 'cutover_review_blocked', 'reason': str(error) if isinstance(error, ReviewBlocked)
            else 'invalid_or_unavailable_input', 'deployment_authorized': False, 'service_actions_performed': False}))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
