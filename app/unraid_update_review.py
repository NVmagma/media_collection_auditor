"""Read-only comparison of Unraid's saved recreation inputs and one container.

This is an observation, never an update or a SQLite binding authorization.
Private XML/environment values stay out of the returned report.
"""
import re
import shlex
from xml.etree import ElementTree as ET

NAME = 'media_collection_auditor'
LIMIT = 2 * 1024 * 1024


class InventoryFormatError(ValueError):
    """Only fixed diagnostic codes, never private XML/parser exception text."""


def parse_template(raw):
    if (not isinstance(raw, bytes) or len(raw) > LIMIT
            or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper()):
        raise InventoryFormatError('xml_size_or_declaration_unsupported')
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        raise InventoryFormatError('xml_parse_failed') from None
    if root.tag != 'Container':
        raise InventoryFormatError('template_root_unsupported')
    if len(root.findall('Name')) != 1:
        raise InventoryFormatError('template_name_count_unsupported')
    return root


def matching_templates(templates):
    """Reject uncertain inventory instead of guessing which file DockerMan picks."""
    matches = []
    for filename, raw in templates:
        root = parse_template(raw)
        if root.findtext('Name') == NAME:
            matches.append((filename, root))
    return matches


def review_update(*, templates, container):
    blockers, warnings = [], []
    report = {'read_only': True, 'automatic_action': 'none', 'update_authorized': False,
              'binding_verified': False, 'status': 'review_required'}
    stage = 'template_inventory'
    try:
        matches, errors = [], {}
        for _, raw in templates:
            try:
                root = parse_template(raw)
            except InventoryFormatError as error:
                code = str(error)  # This class is constructed only with fixed codes above.
                errors[code] = errors.get(code, 0) + 1
                continue
            if root.findtext('Name') == NAME:
                matches.append(root)
        report['template_count'] = len(templates)
        report['matching_template_count'] = len(matches)
        if errors:
            report['inventory_errors'] = errors
            report['diagnostic_stage'] = stage
            report['blockers'] = ['inventory_unreadable_or_unsupported']
            report['warnings'] = []
            return report
        if len(matches) != 1:
            blockers.append('duplicate_internal_container_name' if matches else 'managed_template_missing')
        else:
            root = matches[0]
            stage = 'container_identity'
            if container.get('Name') != '/' + NAME:
                raise ValueError('wrong_container')
            config, host = container['Config'], container['HostConfig']
            stage = 'template_runtime_fields'
            fields = ('Repository', 'Network', 'Privileged', 'ExtraParams', 'PostArgs', 'WebUI', 'Icon')
            if any(len(root.findall(key)) > 1 for key in fields):
                raise ValueError('duplicate_field')
            reference = root.findtext('Repository') or ''
            if not re.fullmatch(r'ghcr\.io/nvmagma/media_collection_auditor@sha256:[0-9a-f]{64}', reference):
                blockers.append('template_image_not_pinned')
            if reference != config.get('Image'):
                blockers.append('image_reference_mismatch')
            if root.findtext('Network') != host.get('NetworkMode'):
                blockers.append('network_mismatch')
            if (root.findtext('Privileged') or '').lower() != 'false' or host.get('Privileged') is not False:
                blockers.append('privileged_configuration')
            if (root.findtext('PostArgs') or '').strip():
                blockers.append('custom_post_arguments')
            stage = 'template_extra_arguments'
            args = shlex.split(root.findtext('ExtraParams') or '')
            if '--read-only' not in args or host.get('ReadonlyRootfs') is not True:
                blockers.append('read_only_root_missing')
            stage = 'template_config_entries'
            expected, seen = {}, set()
            for item in root.findall('Config'):
                key = item.get('Type'), item.get('Target')
                if not key[1] or key in seen:
                    raise ValueError('duplicate_config')
                seen.add(key)
                expected[key] = (item.text or '', item.get('Mode', ''))
            stage = 'container_environment'
            live_env = dict(value.split('=', 1) for value in config.get('Env', []))
            if any(live_env.get(key[1]) != value for key, (value, _) in expected.items() if key[0] == 'Variable'):
                blockers.append('environment_mismatch')
            required = {'AUDITOR_STATE_BACKEND': 'sqlite', 'DRY_RUN': 'true',
                        'SQLITE_STATE_FILE': '/sqlite-control/release/state.db',
                        'ALLOW_FILESYSTEM_DELETE': 'false', 'ALLOW_PERMANENT_DELETE': 'false',
                        'ALLOW_CROSS_FILESYSTEM_MOVES': 'false'}
            if any(live_env.get(key, '').lower() != value or expected.get(('Variable', key), (None,))[0] != value
                   for key, value in required.items()):
                blockers.append('preview_settings_missing_or_unsafe')
            stage = 'container_mounts'
            mounts = container.get('Mounts', [])
            live_mounts = {item['Destination']: item for item in mounts}
            paths = {key[1]: value for key, value in expected.items() if key[0] == 'Path'}
            if len(live_mounts) != len(mounts) or set(paths) != set(live_mounts):
                blockers.append('mount_inventory_mismatch')
            for target, (origin, mode) in paths.items():
                observed = live_mounts.get(target, {})
                if (observed.get('Type') != 'bind' or observed.get('Source') != origin
                        or observed.get('RW') is not (mode.split(',')[0] == 'rw')):
                    blockers.append('mount_binding_mismatch')
            if (paths.get('/media', ('', ''))[1] != 'ro'
                    or any(paths.get(target, ('', ''))[1] != 'rw' for target in ('/sqlite-control', '/app/logs'))):
                blockers.append('preview_mount_layout_missing')
            stage = 'container_ports'
            ports = {key[1] + '/' + mode: [{'HostIp': '', 'HostPort': value}]
                     for key, (value, mode) in expected.items() if key[0] == 'Port'}
            actual_ports = host.get('PortBindings') or {}
            normalized = {key: [{'HostIp': '' if item.get('HostIp', '') == '0.0.0.0' else item.get('HostIp', ''),
                                  'HostPort': item.get('HostPort')} for item in items]
                          for key, items in actual_ports.items()}
            if ports != normalized:
                blockers.append('published_ports_mismatch')
            if not root.findtext('WebUI'):
                warnings.append('webui_link_missing')
            if not root.findtext('Icon'):
                warnings.append('icon_missing')
    except (ValueError, KeyError, TypeError, AttributeError, ET.ParseError):
        blockers.append('inventory_unreadable_or_unsupported')
        report['diagnostic_stage'] = stage
    report['blockers'] = sorted(set(blockers))
    report['warnings'] = sorted(set(warnings))
    if not blockers:
        report['status'] = 'template_matches_observed_container'
    return report
