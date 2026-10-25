"""Actual Docker handoff on two NEW uniquely named disposable containers.

The adapter maps the model's fixed service names into a random fixture namespace,
and admits only its two recorded IDs and new lab binds. The old stand-in sleeps;
the new worker runs the actual image. No production names, files or registry
publication are accessed. This is not an old-worker runtime compatibility claim.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
from urllib.parse import quote

from app import sqlite_preview_cutover as packet
from app.sqlite_preview_activation import _revision
from app.sqlite_preview_template import render_preview_template
from app.state_store import GuardedSQLiteStateStore
from scripts.sqlite_preview_service import Docker, execute_approved, NAME, LABEL, container_id
from scripts.sqlite_preview_cutover_fixture import PreviewCutoverFixtureTests

REFERENCE = 'ghcr.io/nvmagma/media_collection_auditor@sha256:' + '9' * 64
FIXTURE_LABEL = 'io.media-collection-auditor.service-fixture'


class ScopedFixtureEngine:
    def __init__(self, raw, image_id, host_root, nonce):
        self.raw, self.image_id, self.host_root, self.nonce = raw, image_id, host_root, nonce
        self.original = self.preview = None
        self.request_id = None
        self.names = {NAME: 'auditor-service-' + nonce,
                      'old-initial': 'auditor-service-old-' + nonce}

    def image(self, reference):
        if reference != REFERENCE: raise RuntimeError('Fixture registry reference scope changed')
        result = self.raw.image(self.image_id)
        if result['Id'] != self.image_id: raise RuntimeError('Fixture image identity changed')
        result['RepoDigests'] = [REFERENCE]  # Explicit synthetic attestation; no publication claim.
        return result

    def check_id(self, identity):
        container_id(identity)
        if identity not in (self.original, self.preview): raise RuntimeError('ID outside disposable fixture')
        current = self.raw.inspect(identity)
        labels = current['Config'].get('Labels', {})
        if identity == self.original:
            if labels.get(FIXTURE_LABEL) != self.nonce: raise RuntimeError('Original fixture marker changed')
        elif labels.get(LABEL) != self.request_id:
            raise RuntimeError('Preview fixture request marker changed')
        if current['Image'] != self.image_id: raise RuntimeError('Fixture image changed')
        if current.get('HostConfig', {}).get('PortBindings'):
            raise RuntimeError('Fixture must never publish a host port')
        if any(not Path(item['Source']).is_relative_to(self.host_root) for item in current['Mounts']):
            raise RuntimeError('Fixture mount escaped disposable lab')
        return current

    def inspect(self, value, optional=False):
        if re.fullmatch('[0-9a-f]{64}', value):
            current = self.check_id(value)
        else:
            actual = self.names.get(value)
            if actual is None:
                # Reserved role names may be queried before their first rename.
                if not optional: raise RuntimeError('Unknown fixture role name')
                return None
            current = self.raw.inspect(actual, optional=optional)
            if current is None: return None
            current = self.check_id(current['Id'])
        result = deepcopy(current)
        roles = {actual: role for role, actual in self.names.items() if role != 'old-initial'}
        result['Name'] = '/' + roles.get(result['Name'][1:], NAME)
        if result['Id'] == self.original:
            # The stand-in's sleep entrypoint is intentionally not a live worker.
            # Only its service identity/control is under test; legacy JSON load/
            # save compatibility was separately proved with Tower's old image.
            result['Config']['Entrypoint'] = ['python', 'main.py']
            result['Config']['Cmd'] = None
            result['Config']['Image'] = REFERENCE
        return result

    def stop(self, identity): self.check_id(identity); self.raw.stop(identity)
    def start(self, identity): self.check_id(identity); self.raw.start(identity)

    def rename(self, identity, role):
        self.check_id(identity)
        allowed = {NAME, NAME + '_rollback_' + self.original[:12]}
        if self.preview: allowed.add(NAME + '_preview_retained_' + self.preview[:12])
        if role not in allowed: raise RuntimeError('Rename outside fixture role namespace')
        if role not in self.names: self.names[role] = 'auditor-service-' + self.nonce + '-' + str(len(self.names))
        self.raw.rename(identity, self.names[role])

    def create(self, name, payload):
        if name != NAME or self.preview is not None: raise RuntimeError('Single new fixture preview only')
        if payload['Image'] != REFERENCE: raise RuntimeError('Fixture image reference changed')
        if (not payload['HostConfig'].get('ReadonlyRootfs')
                or any(not Path(item['Source']).is_relative_to(self.host_root) for item in payload['HostConfig']['Mounts'])):
            raise RuntimeError('Fixture payload escaped lab')
        self.request_id = payload['Labels'][LABEL]
        local = deepcopy(payload); local['Image'] = self.image_id
        self.preview = self.raw.create(self.names[NAME], local)
        self.check_id(self.preview)
        return self.preview

    def cleanup(self):
        for identity in (self.preview, self.original):
            if identity is not None:
                self.check_id(identity)
                self.raw.request('DELETE', '/containers/' + identity + '?force=1&v=0', statuses=(204,))


def verify():
    image_id = os.environ['EXPECTED_PREVIEW_IMAGE']
    revision = os.environ['EXPECTED_RELEASE_REVISION']
    controller_revision = os.environ['EXPECTED_CONTROLLER_REVISION']
    host_root = Path(os.environ['HOST_FIXTURE_ROOT'])
    if _revision() != revision: raise RuntimeError('Exact accepted image profile required')
    raw = Docker(endpoint='/docker-engine.sock', expected_daemon=os.environ['EXPECTED_DAEMON_ID'])
    nonce = secrets.token_hex(8)
    scope = ScopedFixtureEngine(raw, image_id, host_root, nonce)
    root, logs, control, templates = Path('/packet'), Path('/app/logs'), Path('/sqlite-control'), Path('/unraid-templates')
    case = PreviewCutoverFixtureTests(); case.setUp()
    try:
        # Model Tower's existing logs ownership without changing its real appdata.
        # CAP_CHOWN is supplied only to this disposable fixture setup.
        os.chmod(logs, 0o755)
        os.chown(logs, 99, 100)
        # This creates only an idle fixture container; it never imports an auditor.
        original_payload = {'Image': image_id, 'User': '0:0', 'WorkingDir': '/app',
            'Entrypoint': ['python'], 'Cmd': ['-B', '-c', 'import time; time.sleep(3600)'],
            'Env': ['DRY_RUN=true', 'AUDITOR_STATE_BACKEND=json',
                    'JELLYFIN_HOST_URL=http://127.0.0.1:9', 'JELLYFIN_API_TOKEN=synthetic-token',
                    'INTEGRATION_API_TOKEN=synthetic-integration-token-0123456789abcdef', 'WEB_PORT=8080'],
            'Labels': {FIXTURE_LABEL: nonce}, 'HostConfig': {'NetworkMode': 'bridge',
                'RestartPolicy': {'Name': 'no', 'MaximumRetryCount': 0}, 'Memory': 268435456,
                'PidsLimit': 64, 'Mounts': [{'Type': 'bind', 'Source': str(host_root / name),
                    'Target': target, 'ReadOnly': False} for name, target in (('logs', '/app/logs'), ('media', '/media'))],
                'PortBindings': {}}}
        # No host port is published by the stand-in. The offline model uses an
        # explicit fake port solely to render an XML proposal; the scope adapter
        # strips that publication from the real preview payload below.
        original_payload['HostConfig']['PortBindings'] = {}
        scope.original = raw.create(scope.names['old-initial'], original_payload)
        raw.start(scope.original)
        observed = scope.inspect(scope.original)
        # Keep real IDs/mounts/config/resource observations, with a synthetic
        # offline port binding to exercise the managed-template composition.
        observed['HostConfig']['PortBindings'] = {'8080/tcp': [{'HostIp': '', 'HostPort': '18089'}]}
        original_inspect = scope.inspect
        def model_inspect(value, optional=False):
            result = original_inspect(value, optional)
            if result is not None:
                result['HostConfig']['PortBindings'] = deepcopy(observed['HostConfig']['PortBindings'])
                if result['Id'] == scope.original:
                    changed = {key: [field for field in sorted(set(result.get(key, {})) | set(observed.get(key, {})))
                                     if result.get(key, {}).get(field) != observed.get(key, {}).get(field)]
                               for key in ('Config', 'HostConfig')}
                    changed = {key: value for key, value in changed.items() if value}
                    if result.get('Mounts') != observed.get('Mounts'): changed['Mounts'] = ['mount_metadata']
                    if changed:
                        print(json.dumps({'fixture_observation_changed_fields': changed}))
            return result
        scope.inspect = model_inspect
        original_create = scope.create
        def no_published_port(name, payload):
            local = deepcopy(payload); local['HostConfig']['PortBindings'] = {}
            return original_create(name, local)
        scope.create = no_published_port
        case.root = root; case.old = [observed]; case.inputs()
        original_xml = b'<Container version="2"><Name>media_collection_auditor</Name><Repository>old</Repository></Container>'
        (root / 'original-template.xml').write_bytes(original_xml)
        (templates / 'my-media_collection_auditor.xml').write_bytes(original_xml)
        (logs / 'auditor_config.json').write_bytes((root / 'original-config.json').read_bytes())
        source = (root / 'source-observed.json').read_bytes()
        (logs / 'auditor_state.json').write_bytes(source)
        report = packet.write_review_packet(directory=root, preview_image=image_id,
            rollback_image=image_id, control_host=str(host_root / 'control'), source_revision=revision)
        def identity(path):
            info = path.stat(); return info.st_dev, info.st_ino
        kwargs = dict(directory=root, packet_identity=identity(root), control_identity=identity(control),
            image_id=image_id, reference=REFERENCE, approved_review_sha=hashlib.sha256((root / 'review.json').read_bytes()).hexdigest(),
            daemon_id=os.environ['EXPECTED_DAEMON_ID'], controller_revision=controller_revision, engine=scope)
        result = execute_approved(action='apply', **kwargs)
        if result['status'] != 'preview_service_cutover_complete': raise RuntimeError('Fixture handoff did not complete')
        if raw.inspect(scope.original)['State']['Running']: raise RuntimeError('Original fixture unexpectedly restarted')
        if not raw.inspect(scope.preview)['State']['Running']: raise RuntimeError('Actual preview fixture stopped')
        if (logs / 'auditor_state.json').read_bytes() != source: raise RuntimeError('Fixture JSON changed')
        before = GuardedSQLiteStateStore(control / 'release' / 'state.db').load_with_revision()
        restored = execute_approved(action='rollback', **kwargs)
        if restored['status'] != 'original_auditor_recovered': raise RuntimeError('Fixture recovery incomplete')
        if not raw.inspect(scope.original)['State']['Running'] or raw.inspect(scope.preview)['State']['Running']:
            raise RuntimeError('Fixture recovery service state differs')
        if (templates / 'my-media_collection_auditor.xml').read_bytes() != original_xml:
            raise RuntimeError('Fixture managed template not restored')
        if (logs / 'auditor_config.json').read_bytes() != (root / 'original-config.json').read_bytes():
            raise RuntimeError('Fixture settings not restored')
        if GuardedSQLiteStateStore(control / 'release' / 'state.db').load_with_revision() != before:
            raise RuntimeError('Fixture SQL changed')
        print(json.dumps({'status': 'actual_scoped_service_handoff_recovery_verified',
            'fixture_only': True, 'original_stand_in': 'idle_process_not_legacy_worker',
            'preview_runtime': 'actual_image_and_authenticated_api', 'source_json_unchanged': True,
            'managed_template_restored': True, 'production_authorized': False,
            'registry_publication_performed': False, 'host_ports_published': False}))
    finally:
        scope.cleanup()
        case.doCleanups()


if __name__ == '__main__':
    verify()
