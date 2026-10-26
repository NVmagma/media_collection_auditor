"""Render a PRIVATE proposed Unraid template; never install it or control Docker.

The approved registry digest is deliberately a placeholder until publication is
reviewed. The template is data for the cutover packet, not an activation permit.
Original XML remains byte-exact in the packet for verified settings recovery.
"""
from copy import deepcopy
from html import unescape
import re
import shlex
from xml.etree import ElementTree as ET

REFERENCE = '@APPROVED_PREVIEW_REFERENCE@'
RUNTIME_DEFAULTS = frozenset(('PATH', 'PYTHON_VERSION', 'PYTHON_SHA256', 'PYTHON_GET_PIP_URL',
    'PYTHON_GET_PIP_SHA256', 'PYTHON_PIP_VERSION', 'PYTHON_SETUPTOOLS_VERSION'))


class TemplateReviewBlocked(RuntimeError):
    pass


def render_preview_template(*, original, env, plan, review):
    """Rebuild runtime fields from the reviewed container, preserving UI metadata.

    Original extra/post arguments are never carried into the new execution plan.
    The selected template must describe a single ordinary managed container.
    Unsupported or stale variable/port bindings require private review.
    """
    if not isinstance(original, bytes) or b'<!DOCTYPE' in original.upper() or b'<!ENTITY' in original.upper():
        raise TemplateReviewBlocked('unsupported_template_declaration')
    root = ET.fromstring(original)
    if root.tag != 'Container' or root.get('version', '2') != '2':
        raise TemplateReviewBlocked('unsupported_managed_template_format')
    for name in ('Name', 'Repository', 'Network', 'Privileged', 'ExtraParams', 'PostArgs', 'WebUI', 'CPUset',
                 'MyIP', 'MyMAC', 'Memory', 'ExtraNetworks', 'TailscaleEnabled'):
        if len(root.findall(name)) > 1:
            raise TemplateReviewBlocked('duplicate_managed_template_runtime_field')
    if root.findtext('Name') != 'media_collection_auditor':
        raise TemplateReviewBlocked('unexpected_managed_template')
    if (any((root.findtext(key) or '').strip() for key in ('ExtraNetworks', 'MyIP', 'MyMAC'))
            or (root.findtext('TailscaleEnabled') or '').strip().lower() == 'true'):
        raise TemplateReviewBlocked('custom_template_network_controls_require_review')
    if review['network_mode'] not in ('bridge', 'default', 'host'):
        raise TemplateReviewBlocked('unsupported_template_network')
    configs, seen = {}, set()
    for item in root.findall('Config'):
        kind, target = item.get('Type'), item.get('Target')
        if kind not in ('Path', 'Port', 'Variable', 'Label') or not isinstance(target, str) or not target:
            raise TemplateReviewBlocked('unsupported_managed_template_config')
        key = kind, target
        if key in seen:
            raise TemplateReviewBlocked('duplicate_managed_template_config')
        seen.add(key); configs[key] = deepcopy(item)
        if kind == 'Variable' and target not in env and target not in RUNTIME_DEFAULTS:
            raise TemplateReviewBlocked('template_variable_absent_from_live_container')
    for item in root.findall('Config'):
        root.remove(item)

    def field(name, value):
        item = root.find(name)
        if item is None: item = ET.SubElement(root, name)
        item.text = value

    def config(kind, target, value, mode='', name=None):
        # DockerMan performs an additional HTML decode and tag filtering after
        # XML parsing. Refuse values that would change rather than silently
        # changing a credential or adding a shell interpretation layer.
        if any(not isinstance(text, str) or unescape(text) != text or '<' in text or '>' in text
               for text in (target, value)):
            raise TemplateReviewBlocked('template_value_not_losslessly_representable')
        item = configs.get((kind, target), ET.Element('Config', {'Type': kind, 'Target': target,
            'Name': name or target, 'Display': 'advanced', 'Required': 'false', 'Mask': 'true'}))
        item.set('Type', kind); item.set('Target', target); item.set('Mode', mode)
        item.set('Default', value); item.text = value
        if kind != 'Variable': item.set('Mask', 'false')
        if any(part in target.upper() for part in ('TOKEN', 'KEY', 'PASSWORD', 'SECRET', 'WEBHOOK')):
            item.set('Mask', 'true')
        root.append(item)

    field('Repository', REFERENCE)
    field('Registry', 'https://ghcr.io/')
    field('Network', 'bridge' if review['network_mode'] == 'default' else review['network_mode'])
    field('Privileged', 'false'); field('PostArgs', ''); field('CPUset', ''); field('Memory', ''); field('MyIP', '')
    webui = 'http://[IP]:[PORT:' + env.get('WEB_PORT', '8080') + ']/'
    field('WebUI', webui)
    webui_label_seen = False
    args = plan.get('create_argv_template')
    if not isinstance(args, list) or args[0] != 'create' or args[-1] != review['preview_image_id']:
        raise TemplateReviewBlocked('reviewed_create_arguments_required')
    extra, destinations = [], set()
    for arg in args[1:-1]:
        if arg.startswith(('--name=', '--network=', '--env-file=')):
            continue
        if arg.startswith('--mount='):
            pieces = arg[len('--mount='):].split(',')
            values = dict(piece.split('=', 1) for piece in pieces if '=' in piece)
            target, origin = values.get('dst'), values.get('src')
            if values.get('type') != 'bind' or target not in ('/media', '/app/logs', '/sqlite-control') or target in destinations:
                raise TemplateReviewBlocked('unsupported_template_bind')
            destinations.add(target)
            mode = 'ro' if 'readonly' in pieces else 'rw'
            propagation = values.get('bind-propagation', 'rprivate')
            if propagation == 'rslave': mode += ',slave'
            elif propagation != 'rprivate': raise TemplateReviewBlocked('unsupported_template_bind_propagation')
            config('Path', target, origin, mode)
        elif arg.startswith('--publish='):
            continue  # Port configs below preserve the explicitly reviewed mapping.
        elif arg.startswith('--label='):
            key, separator, value = arg[len('--label='):].partition('=')
            if not separator: raise TemplateReviewBlocked('invalid_template_label')
            if key == 'net.unraid.docker.webui':
                value = webui
                webui_label_seen = True
            config('Label', key, value)
        else:
            if not arg.startswith(('--pull=', '--user=', '--restart=', '--read-only', '--tmpfs=',
                    '--hostname=', '--domainname=', '--memory=', '--memory-swap=', '--memory-reservation=',
                    '--pids-limit=', '--cpu-shares=', '--cpu-period=', '--cpu-quota=', '--cpus=', '--cpuset-cpus=',
                    '--memory-swappiness=', '--cgroupns=', '--cap-add=', '--cap-drop=', '--security-opt=',
                    '--dns=', '--dns-option=', '--dns-search=', '--add-host=', '--log-driver=', '--log-opt=')):
                raise TemplateReviewBlocked('unsupported_template_extra_parameter')
            extra.append(arg)
    if destinations != {'/media', '/app/logs', '/sqlite-control'}:
        raise TemplateReviewBlocked('complete_template_bind_layout_required')
    if not webui_label_seen:
        config('Label', 'net.unraid.docker.webui', webui)
    ports = set()
    for item in review['published_ports']:
        if item['host_ip'] not in ('', '0.0.0.0'):
            raise TemplateReviewBlocked('template_interface_specific_port_requires_review')
        target, protocol = item['container'].split('/')
        if target in ports:
            raise TemplateReviewBlocked('template_duplicate_port_target_requires_review')
        ports.add(target)
        config('Port', target, item['host_port'], protocol)
    for key, value in sorted(env.items()):
        config('Variable', key, value)
    extra_text = shlex.join(extra)
    if unescape(extra_text) != extra_text or '<' in extra_text or '>' in extra_text:
        raise TemplateReviewBlocked('template_extra_value_not_losslessly_representable')
    field('ExtraParams', extra_text)
    root.set('version', '2')
    raw = ET.tostring(root, encoding='utf-8', xml_declaration=True) + b'\n'
    summary = {'managed_template_plan': 'prepared_not_installed',
        'template_registry_reference': 'approval_placeholder', 'template_environment_entries': len(env),
        'template_media_read_only': True, 'template_control_mount_present': True,
        'template_service_changes_performed': False}
    return raw, summary


def bind_published_reference(*, proposed, reference):
    """Return final XML bytes only; caller still must verify cached image identity.

    No registry lookup, publication, file replacement or service control occurs.
    A tag or another repository cannot replace the approved digest reference.
    """
    if not isinstance(reference, str) or not re.fullmatch(
            r'ghcr\.io/nvmagma/media_collection_auditor@sha256:[0-9a-f]{64}', reference):
        raise TemplateReviewBlocked('immutable_approved_preview_repository_required')
    root = ET.fromstring(proposed)
    items = root.findall('Repository')
    if len(items) != 1 or items[0].text != REFERENCE:
        raise TemplateReviewBlocked('unbound_proposed_template_required')
    items[0].text = reference
    return ET.tostring(root, encoding='utf-8', xml_declaration=True) + b'\n'
