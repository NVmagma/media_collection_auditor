"""Private Unraid template planning, synthetic metadata only; no service calls."""
from copy import deepcopy
import json
from pathlib import Path
import shlex
import unittest
from xml.etree import ElementTree as ET

from app.sqlite_preview_template import render_preview_template, bind_published_reference, TemplateReviewBlocked, REFERENCE
from scripts.sqlite_preview_cutover_fixture import PreviewCutoverFixtureTests, SECRET

ORIGINAL = b'''<Container version="2"><Name>media_collection_auditor</Name>
<Repository>ghcr.io/nvmagma/media_collection_auditor:feature-sqlite</Repository>
<Overview>Keep this description</Overview><Icon>http://fixture.invalid/icon.png</Icon>
<ExtraParams>--privileged --entrypoint=/stale</ExtraParams><PostArgs>stale-command</PostArgs>
<Memory>123m</Memory><CPUset>5</CPUset>
<Config Type="Variable" Target="INTEGRATION_API_TOKEN" Name="Existing token" Mask="false">stale</Config>
<Config Type="Path" Target="/media" Name="Media" Mode="rw">/old/path</Config>
<Config Type="Port" Target="8080" Mode="tcp">9999</Config></Container>'''


def prepare_private_packet(directory):
    case = PreviewCutoverFixtureTests(); case.setUp()
    try:
        case.root = Path(directory)
        case.inputs()
        (case.root / 'original-template.xml').write_bytes(ORIGINAL)
    finally:
        case.doCleanups()


def verify_private_packet(directory):
    import hashlib
    root = Path(directory)
    report = json.loads((root / 'review.json').read_bytes())
    raw = (root / 'proposed-template.xml').read_bytes()
    env = dict(line.split('=', 1) for line in (root / 'preview.env').read_text().splitlines())
    parsed = ET.fromstring(raw)
    assert report['status'] == 'cutover_review_prepared' and not report['deployment_authorized']
    assert report['managed_template_plan'] == 'prepared_not_installed'
    assert report['proposed_template_sha256'] == hashlib.sha256(raw).hexdigest()
    assert SECRET not in (root / 'review.json').read_text()
    assert parsed.findtext('Repository') == REFERENCE
    assert {item.get('Target'): item.text or '' for item in parsed.findall("Config[@Type='Variable']")} == env
    assert parsed.find("Config[@Target='/media']").get('Mode') == 'ro'
    assert parsed.find("Config[@Target='/sqlite-control']") is not None
    assert all((root / name).stat().st_mode & 0o777 == 0o600 for name in (
        'review.json', 'preview.env', 'proposed-config.json', 'container-plan.json', 'proposed-template.xml'))
    print('status=actual_private_packet_template_verified')


class PreviewTemplateFixtureTests(unittest.TestCase):
    def setUp(self):
        self.case = PreviewCutoverFixtureTests(); self.case.setUp(); self.addCleanup(self.case.doCleanups)
        self.review, self.plan, self.env, _ = self.case.render()

    def render(self, original=ORIGINAL, **changes):
        return render_preview_template(original=original, env=changes.get('env', self.env),
            plan=changes.get('plan', self.plan), review=changes.get('review', self.review))

    def test_template_matches_reviewed_paths_ports_and_settings_without_installing(self):
        raw, summary = self.render(); root = ET.fromstring(raw)
        configs = {(item.get('Type'), item.get('Target')): item for item in root.findall('Config')}
        self.assertEqual(root.findtext('Repository'), REFERENCE)
        self.assertEqual(root.findtext('Network'), 'bridge')
        self.assertEqual(root.findtext('WebUI'), 'http://[IP]:[PORT:8080]/')
        self.assertEqual(configs['Label', 'net.unraid.docker.webui'].text, root.findtext('WebUI'))
        self.assertEqual(root.findtext('Privileged'), 'false')
        self.assertEqual(root.findtext('Overview'), 'Keep this description')
        self.assertEqual(configs['Path', '/media'].get('Mode'), 'ro')
        self.assertEqual(configs['Path', '/sqlite-control'].text, self.review['control_host_path'])
        self.assertEqual(configs['Port', '8080'].text, '10012')
        self.assertEqual({k[1]: v.text or '' for k, v in configs.items() if k[0] == 'Variable'}, self.env)
        self.assertFalse(summary['template_service_changes_performed'])
        self.assertNotIn(SECRET, json.dumps(summary))

    def test_stale_extra_commands_and_root_resource_fields_cannot_override_plan(self):
        raw, _ = self.render(); root = ET.fromstring(raw)
        args = shlex.split(root.findtext('ExtraParams'))
        self.assertIn('--read-only', args); self.assertIn('--user=0:0', args)
        self.assertIn('--restart=no', args); self.assertIn('--memory=256000000', args)
        self.assertNotIn('--privileged', args)
        self.assertNotIn('--entrypoint=/stale', args)
        self.assertFalse(root.findtext('Memory')); self.assertFalse(root.findtext('CPUset'))
        self.assertFalse(root.findtext('PostArgs'))

    def test_token_is_private_and_masked_even_if_old_template_exposed_it(self):
        raw, _ = self.render(); root = ET.fromstring(raw)
        token = root.find("Config[@Target='INTEGRATION_API_TOKEN']")
        self.assertEqual(token.text, SECRET); self.assertEqual(token.get('Mask'), 'true')
        self.assertEqual(token.get('Name'), 'Existing token')

    def test_shell_and_xml_characters_are_data_and_defaults_match_values(self):
        env = dict(self.env, INTEGRATION_API_TOKEN="literal '$() `ticks` & unknown")
        raw, _ = self.render(env=env)
        token = ET.fromstring(raw).find("Config[@Target='INTEGRATION_API_TOKEN']")
        self.assertEqual(token.text, env['INTEGRATION_API_TOKEN'])
        self.assertEqual(token.get('Default'), token.text)

    def test_lossy_entity_or_tag_values_are_rejected_instead_of_changing_credentials(self):
        for value in ('literal &quot; credential', '<private-token>', 'literal &#65;'):
            with self.subTest(value=value), self.assertRaises(TemplateReviewBlocked):
                self.render(env=dict(self.env, INTEGRATION_API_TOKEN=value))

    def test_rslave_bind_maps_to_supported_unraid_slave_mode(self):
        plan = deepcopy(self.plan)
        plan['create_argv_template'] = [arg.replace('bind-propagation=rprivate', 'bind-propagation=rslave')
                                      for arg in plan['create_argv_template']]
        raw, _ = self.render(plan=plan)
        self.assertEqual(ET.fromstring(raw).find("Config[@Target='/media']").get('Mode'), 'ro,slave')

    def test_stale_variables_duplicate_targets_and_device_configs_require_review(self):
        for config in ('<Config Type="Variable" Target="UNKNOWN_OLD_VARIABLE">x</Config>',
                '<Config Type="Path" Target="/media">/extra</Config>', '<Config Type="Device" Target="/dev/sda">/dev/sda</Config>'):
            raw = ORIGINAL.replace(b'</Container>', config.encode() + b'</Container>')
            with self.subTest(config=config), self.assertRaises(TemplateReviewBlocked): self.render(raw)

    def test_custom_network_mac_and_tailscale_controls_require_review(self):
        for item in ('<ExtraNetworks>other</ExtraNetworks>', '<MyIP>10.0.0.99</MyIP>',
                     '<MyMAC>00:11:22:33:44:55</MyMAC>', '<TailscaleEnabled>true</TailscaleEnabled>'):
            with self.subTest(item=item), self.assertRaises(TemplateReviewBlocked):
                self.render(ORIGINAL.replace(b'</Container>', item.encode() + b'</Container>'))

    def test_wrong_name_duplicate_fields_and_entity_declarations_are_refused(self):
        for raw in (ORIGINAL.replace(b'<Name>media_collection_auditor</Name>', b'<Name>other</Name>'),
                ORIGINAL.replace(b'</Container>', b'<Repository>other</Repository></Container>'),
                b'<!DOCTYPE Container [<!ENTITY secret "private">]>' + ORIGINAL):
            with self.subTest(raw=raw[:40]), self.assertRaises(TemplateReviewBlocked): self.render(raw)

    def test_interface_specific_port_is_not_silently_widened(self):
        review = deepcopy(self.review); review['published_ports'][0]['host_ip'] = '127.0.0.1'
        with self.assertRaises(TemplateReviewBlocked): self.render(review=review)

    def test_registry_binding_requires_exact_repository_digest_and_does_not_install(self):
        raw, _ = self.render(); reference = 'ghcr.io/nvmagma/media_collection_auditor@sha256:' + 'f' * 64
        bound = bind_published_reference(proposed=raw, reference=reference)
        self.assertEqual(ET.fromstring(bound).findtext('Repository'), reference)
        self.assertEqual(ET.fromstring(raw).findtext('Repository'), REFERENCE)
        for invalid in ('ghcr.io/nvmagma/media_collection_auditor:latest',
                'ghcr.io/other/image@sha256:' + 'f' * 64):
            with self.assertRaises(TemplateReviewBlocked): bind_published_reference(proposed=raw, reference=invalid)
        with self.assertRaises(TemplateReviewBlocked): bind_published_reference(proposed=bound, reference=reference)


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(PreviewTemplateFixtureTests))
    if not result.wasSuccessful() or result.testsRun != 11 or result.skipped: raise SystemExit(1)
    print(json.dumps({'status': 'private_unraid_template_plan_verified', 'tests': result.testsRun,
        'fixture_only': True, 'service_actions_performed': False, 'registry_publication_performed': False}))
