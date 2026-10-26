"""Fixture-only update/recovery state machine; no production launcher exists.

The supplied engine must enforce recorded fixture IDs, labels and private mounts.
Every external effect follows durable intent. Errors propagate without retries,
container removal, automatic restoration, or discovery/adoption by name.
"""
import hashlib
import os
import re
from app.sqlite_disposable_restore import _write_private
from app.sqlite_json import parse_unique_json
from app.sqlite_release_recovery import _encode, _local
from app.sqlite_scheduled_paths import scan_held_directory
from scripts.sqlite_preview_service import container_id, validate_original, validate_preview

PHASES = ('old_stop_requested', 'old_stopped', 'old_archive_requested', 'old_archived',
          'replacement_create_requested', 'replacement_created', 'replacement_start_requested',
          'replacement_started', 'replacement_healthy', 'template_install_requested',
          'template_installed', 'update_complete')


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


class UpdateJournal:
    def __init__(self, parent, prefix='update'):
        if prefix not in ('update', 'recovery'):
            raise ValueError('Known journal prefix required')
        self.parent, self.prefix, self.sequence, self.previous = parent, prefix, 0, None

    def begin(self, request):
        raw = _encode(request)
        _write_private(self.parent, self.prefix+'-request.json', raw)
        self.previous = _sha(raw)

    def event(self, phase, **values):
        self.sequence += 1
        raw = _encode({'sequence': self.sequence, 'previous_sha256': self.previous, 'phase': phase, **values})
        _write_private(self.parent, self.prefix+'-%04d.json' % self.sequence, raw)
        self.previous = _sha(raw)


def read_update(parent):
    raw = _local(parent, 'update-request.json')[0]; request = parse_unique_json(raw)
    if (request.get('schema_version') != 1 or request.get('fixture_only') is not True
            or request.get('automatic_restoration') is not False):
        raise RuntimeError('Known fixture request required')
    previous, phases, replacement = _sha(raw), [], None
    with scan_held_directory(parent) as entries:
        names = sorted(item.name for item in entries if re.fullmatch('update-[0-9]{4}\\.json', item.name))
    if len(names) > len(PHASES):
        raise RuntimeError('Unexpected update history')
    for number, name in enumerate(names, 1):
        raw = _local(parent, name)[0]; event = parse_unique_json(raw)
        if (name != 'update-%04d.json' % number or event.get('sequence') != number
                or event.get('previous_sha256') != previous or event.get('phase') != PHASES[number-1]):
            raise RuntimeError('Changed or incomplete update history')
        if event['phase'] == 'replacement_created': replacement = container_id(event.get('container_id'))
        if 'container_id' in event and event['container_id'] != replacement:
            raise RuntimeError('Update container identity changed')
        phases.append(event['phase']); previous = _sha(raw)
    try:
        os.stat('update-%04d.json' % (len(names)+1), dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        raise RuntimeError('Update history enumeration incomplete')
    return request, phases, replacement


def _roles(captured):
    old = container_id(captured['Id']); name = captured['Name'].removeprefix('/')
    # This experimental transaction cannot address the production service name.
    if not re.fullmatch(r'auditor-[a-z0-9-]{8,100}', name):
        raise ValueError('Unique disposable service name required')
    return old, name, name+'-rollback-'+old[:12]


def _preview(live, *, role, **kwargs):
    if live.get('Name') != '/'+role:
        raise RuntimeError('Replacement fixture role changed')
    # Existing preview validation has a fixed production role. Normalize only
    # after proving the actual unique fixture role; never address that name.
    validate_preview({**live, 'Name': '/media_collection_auditor'}, **kwargs)


def apply_fixture_update(*, engine, journal, captured, payload, image_id, attempt,
                         validate_data, health, install_template):
    engine.assert_fixture()
    old, name, retained = _roles(captured)
    container_id(attempt)
    if payload.get('Image') != image_id:
        raise ValueError('Exact fixture candidate image required')
    validate_original(engine.inspect(old), captured, name=name, running=True)
    if engine.inspect(retained, optional=True) is not None:
        raise RuntimeError('Retained fixture name occupied')
    validate_data()
    journal.begin({'schema_version': 1, 'fixture_only': True, 'old_id': old, 'attempt': attempt,
        'image_id': image_id, 'captured_sha256': _sha(_encode(captured)),
        'payload_sha256': _sha(_encode(payload)), 'automatic_restoration': False})
    journal.event('old_stop_requested'); engine.stop(old)
    validate_original(engine.inspect(old), captured, name=name, running=False)
    journal.event('old_stopped')
    validate_data()  # A new backup/preparation observation must still match after stop.
    journal.event('old_archive_requested'); engine.rename(old, retained)
    validate_original(engine.inspect(old), captured, name=retained, running=False)
    journal.event('old_archived')
    if engine.inspect(name, optional=True) is not None:
        raise RuntimeError('Fixture service name occupied')
    journal.event('replacement_create_requested'); new = engine.create(name, payload)
    journal.event('replacement_created', container_id=new)
    _preview(engine.inspect(new), role=name, identity=new, image_id=image_id, request_id=attempt, payload=payload, running=False)
    journal.event('replacement_start_requested', container_id=new); engine.start(new)
    _preview(engine.inspect(new), role=name, identity=new, image_id=image_id, request_id=attempt, payload=payload, running=True)
    journal.event('replacement_started', container_id=new)
    health(engine.inspect(new)); validate_data()
    journal.event('replacement_healthy', container_id=new)
    journal.event('template_install_requested', container_id=new); install_template()
    journal.event('template_installed', container_id=new)
    validate_original(engine.inspect(old), captured, name=retained, running=False)
    _preview(engine.inspect(new), role=name, identity=new, image_id=image_id, request_id=attempt, payload=payload, running=True)
    journal.event('update_complete', container_id=new)
    return {'status': 'fixture_update_complete', 'fixture_only': True, 'old_container_retained': True,
            'automatic_restoration': False, 'production_authorized': False}


def recover_fixture_update(*, engine, journal, parent, captured, payload, image_id, attempt,
                           validate_data, restore_template, health, reviewed_new_id=None):
    engine.assert_fixture()
    old, name, retained = _roles(captured)
    request, phases, new = read_update(parent)
    if (request.get('old_id') != old or request.get('attempt') != attempt
            or request.get('image_id') != image_id or request.get('payload_sha256') != _sha(_encode(payload))
            or request.get('captured_sha256') != _sha(_encode(captured))):
        raise RuntimeError('Exact reviewed fixture request required')
    if reviewed_new_id is not None:
        reviewed_new_id = container_id(reviewed_new_id)
        if new is not None and new != reviewed_new_id:
            raise RuntimeError('Reviewed replacement differs from journal')
        new = reviewed_new_id
    if 'replacement_create_requested' in phases and new is None:
        raise RuntimeError('Uncertain create requires explicit replacement ID review')
    current = engine.inspect(old)
    if current['Name'] not in ('/'+name, '/'+retained):
        raise RuntimeError('Old fixture role changed')
    validate_original(current, captured, name=current['Name'][1:], running=False)
    if new is not None:
        observed = engine.inspect(new)
        _preview(observed, role=name, identity=new, image_id=image_id, request_id=attempt, payload=payload,
                         running=observed['State']['Running'])
    validate_data()  # Diverged state must never silently roll back to an old snapshot.
    journal.begin({'schema_version': 1, 'fixture_only': True, 'old_id': old, 'new_id': new,
                   'attempt': attempt, 'automatic_restoration': False})
    if new is not None and engine.inspect(new)['State']['Running']:
        journal.event('replacement_stop_requested', container_id=new); engine.stop(new)
        _preview(engine.inspect(new), role=name, identity=new, image_id=image_id, request_id=attempt,
                         payload=payload, running=False)
        journal.event('replacement_stopped', container_id=new)
    validate_data()
    journal.event('template_restore_requested'); restore_template(); journal.event('template_restored')
    if new is not None:
        journal.event('replacement_retain_requested', container_id=new)
        engine.rename(new, name+'-replacement-retained-'+new[:12])
        journal.event('replacement_retained', container_id=new)
    if current['Name'] != '/'+name:
        journal.event('old_name_restore_requested'); engine.rename(old, name); journal.event('old_name_restored')
    validate_original(engine.inspect(old), captured, name=name, running=False)
    journal.event('old_start_requested'); engine.start(old)
    validate_original(engine.inspect(old), captured, name=name, running=True)
    health(engine.inspect(old)); journal.event('recovery_complete')
    return {'status': 'fixture_original_recovered', 'fixture_only': True,
            'replacement_retained': new is not None, 'automatic_restoration': False, 'production_authorized': False}
