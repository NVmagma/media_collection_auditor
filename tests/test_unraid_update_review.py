"""Synthetic private templates: no Docker daemon, no production paths."""
from copy import deepcopy
import json
import subprocess
import sys
from xml.etree import ElementTree as ET

from app.unraid_update_review import review_update

REFERENCE = 'ghcr.io/nvmagma/media_collection_auditor@sha256:' + 'a' * 64
SECRET = 'private-token-never-print'


def fixture():
    root = ET.fromstring('<Container><Name>media_collection_auditor</Name>'
        '<Network>bridge</Network><Privileged>false</Privileged>'
        '<ExtraParams>--read-only --cap-drop=ALL</ExtraParams><WebUI>http://[IP]:[PORT:8080]/</WebUI></Container>')
    ET.SubElement(root, 'Repository').text = REFERENCE
    env = {'AUDITOR_STATE_BACKEND': 'sqlite', 'DRY_RUN': 'true',
           'SQLITE_STATE_FILE': '/sqlite-control/release/state.db',
           'ALLOW_FILESYSTEM_DELETE': 'false', 'ALLOW_PERMANENT_DELETE': 'false',
           'ALLOW_CROSS_FILESYSTEM_MOVES': 'false', 'INTEGRATION_API_TOKEN': SECRET}
    for key, value in env.items():
        ET.SubElement(root, 'Config', Type='Variable', Target=key).text = value
    mounts = []
    for target, mode in (('/media', 'ro'), ('/app/logs', 'rw'), ('/sqlite-control', 'rw')):
        origin = '/private-fixture' + target
        ET.SubElement(root, 'Config', Type='Path', Target=target, Mode=mode).text = origin
        mounts.append({'Type': 'bind', 'Source': origin, 'Destination': target, 'RW': mode == 'rw'})
    ET.SubElement(root, 'Config', Type='Port', Target='8080', Mode='tcp').text = '8089'
    container = {'Name': '/media_collection_auditor', 'Config': {'Image': REFERENCE,
        'Env': [key + '=' + value for key, value in env.items()]}, 'HostConfig': {
        'NetworkMode': 'bridge', 'Privileged': False, 'ReadonlyRootfs': True,
        'PortBindings': {'8080/tcp': [{'HostIp': '', 'HostPort': '8089'}]}}, 'Mounts': mounts}
    return root, container


def review(root, container, extra=()):
    return review_update(templates=[('current.xml', ET.tostring(root)), *extra], container=container)


def test_matching_is_observation_not_update_or_binding_permission():
    root, container = fixture()
    result = review(root, container)
    assert result['status'] == 'template_matches_observed_container'
    assert result['update_authorized'] is False and result['binding_verified'] is False
    assert SECRET not in json.dumps(result) and '/private-fixture' not in json.dumps(result)


def test_old_filename_with_same_internal_name_blocks_even_if_current_matches():
    root, container = fixture()
    old = deepcopy(root); old.find('Repository').text = 'stale'
    result = review(root, container, [('my-media_archiver.xml', ET.tostring(old))])
    assert result['blockers'] == ['duplicate_internal_container_name']


def test_stale_image_and_lost_control_mount_are_reported_without_private_values():
    root, container = fixture()
    root.find('Repository').text = 'ghcr.io/nvmagma/media_collection_auditor:latest'
    root.remove(root.find("Config[@Target='/sqlite-control']"))
    result = review(root, container)
    assert {'image_reference_mismatch', 'template_image_not_pinned', 'mount_inventory_mismatch',
            'preview_mount_layout_missing'} <= set(result['blockers'])
    assert SECRET not in json.dumps(result)


def test_settings_mount_ports_and_root_drift_are_detected():
    root, container = fixture()
    container['Config']['Env'][1] = 'DRY_RUN=false'
    container['Mounts'][0]['RW'] = True
    container['HostConfig']['ReadonlyRootfs'] = False
    container['HostConfig']['PortBindings']['8080/tcp'][0]['HostPort'] = '9999'
    assert {'environment_mismatch', 'preview_settings_missing_or_unsafe', 'mount_binding_mismatch',
            'read_only_root_missing', 'published_ports_mismatch'} <= set(review(root, container)['blockers'])


def test_unrelated_template_is_allowed_but_malformed_or_entity_xml_is_unknown():
    root, container = fixture()
    assert not review(root, container, [('other.xml', b'<Container><Name>other</Name></Container>')])['blockers']
    for raw in (b'broken', b'<!DOCTYPE x><Container><Name>other</Name></Container>'):
        assert 'inventory_unreadable_or_unsupported' in review(root, container, [('bad.xml', raw)])['blockers']


def test_duplicate_fields_configs_and_wrong_inspect_are_rejected():
    root, container = fixture()
    ET.SubElement(root, 'Repository').text = SECRET
    assert review(root, container)['blockers'] == ['inventory_unreadable_or_unsupported']
    root, container = fixture()
    root.append(deepcopy(root.find('Config')))
    assert review(root, container)['blockers'] == ['inventory_unreadable_or_unsupported']
    container['Name'] = '/other'
    assert review(root, container)['blockers'] == ['inventory_unreadable_or_unsupported']


def test_cli_refuses_symlink_without_leaking_target_or_secret(tmp_path):
    root, container = fixture()
    target = tmp_path / 'private-data'; target.write_bytes(ET.tostring(root))
    folder = tmp_path / 'templates'; folder.mkdir()
    (folder / 'linked.xml').symlink_to(target)
    result = subprocess.run([sys.executable, '-B', '-m', 'scripts.unraid_update_review',
        '--templates', str(folder)], input=json.dumps([container]), text=True, capture_output=True)
    assert result.returncode == 2
    assert json.loads(result.stdout)['status'] == 'review_required'
    assert SECRET not in result.stdout + result.stderr
    assert target.read_bytes() == ET.tostring(root)


def test_inventory_diagnostics_count_fixed_codes_without_echoing_xml_or_names():
    root, container = fixture()
    result = review(root, container, [
        (SECRET + '.xml', ('<' + SECRET).encode()),
        ('other.xml', b'<Containers/>'),
        ('missing.xml', b'<Container/>'),
    ])
    assert result['diagnostic_stage'] == 'template_inventory'
    assert result['template_count'] == 4 and result['matching_template_count'] == 1
    assert result['inventory_errors'] == {'xml_parse_failed': 1, 'template_root_unsupported': 1,
                                          'template_name_count_unsupported': 1}
    assert result['status'] == 'review_required'
    assert SECRET not in json.dumps(result)


def test_runtime_failure_identifies_stage_without_private_exception_message():
    root, container = fixture()
    root.find('ExtraParams').text = "'" + SECRET
    result = review(root, container)
    assert result['diagnostic_stage'] == 'template_extra_arguments'
    assert SECRET not in json.dumps(result)


def test_external_doctype_classification_never_returns_identifier_or_private_name():
    root, container = fixture()
    for declaration, expected in (
        (b'<!DOCTYPE html PUBLIC "private-identifier" "https://private.invalid/secret">', ('html', 'public')),
        (b'<!DOCTYPE Container SYSTEM "file:///private/secret">', ('container', 'system')),
        (b'<!DOCTYPE private-secret [ ]>', ('other', 'internal_subset')),
    ):
        result = review(root, container, [('untrusted.xml', declaration + b'<Container><Name>other</Name></Container>')])
        diagnostic = result['declaration_diagnostics'][0]
        assert (diagnostic['doctype_root_kind'], diagnostic['doctype_form']) == expected
        assert result['status'] == 'review_required' and result['update_authorized'] is False
        assert 'private' not in json.dumps(result) and 'secret' not in json.dumps(result)


def test_slave_propagation_is_preserved_and_unexpected_changes_block():
    root, container = fixture()
    root.find("Config[@Target='/media']").set('Mode', 'ro,slave')
    container['Mounts'][0]['Propagation'] = 'rslave'
    assert not review(root, container)['blockers']
    container['Mounts'][0]['Propagation'] = 'rprivate'
    assert 'mount_binding_mismatch' in review(root, container)['blockers']
