"""Candidate review is a non-executable private plan, never a same-image bypass."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from xml.etree import ElementTree as ET
import pytest
from scripts import unraid_update_prepare_fixture as fixtures
from scripts import unraid_update_candidate_review as review
from tests.test_unraid_update_production_prepare import inputs
from app.sqlite_preview_template import REFERENCE

pytestmark=pytest.mark.skipif(sys.platform!='linux',reason='Linux descriptor-bound candidate review')


@pytest.fixture
def ready():
    case=fixtures.ReplacementPrepareTests();case.setUp()
    try:
        args=inputs();current=args['current'];current['Id']='a'*64;current['Image']='sha256:'+'a'*64
        current['State']={'Running':True}
        current['Config']['Env']=[key+'='+value for key,value in case.env.items()]
        current['Config']['Labels']={'org.opencontainers.image.revision':'a'*40,'custom.label':'preserved'}
        for item in current['Mounts']:
            item['Source']={'/app/logs':'/host/old-logs','/sqlite-control':'/host/old-control','/media':'/host/media'}[item['Destination']]
        root=ET.fromstring(args['template'])
        for item in list(root.findall('Config')):
            if item.get('Type')=='Variable':root.remove(item)
        for key,value in case.env.items():
            item=ET.SubElement(root,'Config',Type='Variable',Target=key);item.text=value
        template=ET.tostring(root)
        for name,raw in (('current.inspect.json',json.dumps(current).encode()),('current-template.xml',template)):
            (case.backup/name).write_bytes(raw)
        receipt_path=case.backup/'backup-complete.json';receipt=json.loads(receipt_path.read_bytes())
        for name in ('current.inspect.json','current-template.xml'):
            receipt['sha256'][name]=hashlib.sha256((case.backup/name).read_bytes()).hexdigest()
        receipt_path.write_text(json.dumps(receipt))
        case.fingerprint=hashlib.sha256(receipt_path.read_bytes()).hexdigest()
        case.backup_before={p.name:p.read_bytes() for p in case.backup.iterdir()}
        case.prepare()
        output=case.root/'candidate-review';output.mkdir(mode=0o700)
        options=dict(backup=case.backup,backup_identity=fixtures.identity(case.backup),fingerprint=case.fingerprint,
            logs=case.logs,control=case.control,old_logs=case.source.parent,old_control=case.old_control,
            output=output,output_identity=fixtures.identity(output),live=current,image=case.image,
            host_logs='/host/new/logs',host_control='/host/new/control',
            templates=lambda:[('my-media_collection_auditor.xml',template)])
        yield case,options
    finally:case.doCleanups()


def test_review_preserves_state_and_marks_publication_and_handoff_pending(ready):
    case,options=ready
    before=deepcopy(options['live'])
    report=review.review_candidate(**options)
    assert report['status']=='candidate_review_prepared' and report['backup_matches_current_observation']
    assert not report['deployment_authorized'] and not report['executable_payload_prepared']
    assert report['image_reference_status']=='publication_required' and not report['writer_quiescence_verified']
    payload=json.loads((options['output']/'proposed-container.json').read_bytes())
    template=ET.fromstring((options['output']/'proposed-template.xml').read_bytes())
    assert payload['Image']==REFERENCE and template.findtext('Repository')==REFERENCE
    assert payload['Labels']['org.opencontainers.image.revision']=='b'*40
    assert payload['Labels']['custom.label']=='preserved'
    assert template.findtext('WebUI')=='http://[IP]:[PORT:8080]/'
    assert payload['HostConfig']['ReadonlyRootfs'] is True
    assert next(item for item in payload['HostConfig']['Mounts'] if item['Target']=='/media')['ReadOnly'] is True
    assert payload['HostConfig']['PortBindings']==before['HostConfig']['PortBindings']
    assert 'fixture-private-secret' not in json.dumps(report)
    assert options['live']==before
    assert all(path.stat().st_mode&0o777==0o600 for path in options['output'].iterdir())
    case.unchanged()


@pytest.mark.parametrize('change',['old_config','old_state','prepared_env','template_duplicate','live_image'])
def test_changed_inputs_refuse_before_review_files(ready,change):
    case,options=ready
    if change=='old_config':case.saved.write_text('{"changed":"private"}')
    elif change=='old_state':case.source.write_text('{}')
    elif change=='prepared_env':
        with (case.logs/'runtime.env').open('a') as stream:stream.write('PRIVATE=changed\n')
    elif change=='template_duplicate':
        old=options['templates']();options['templates']=lambda:old+old
    else:options['live']['Image']='sha256:'+'f'*64
    with pytest.raises((RuntimeError,ValueError)):review.review_candidate(**options)
    assert not list(options['output'].iterdir())


def test_change_during_plan_write_retains_partial_without_completion(ready,monkeypatch):
    case,options=ready
    original=review._write_private
    def write(fd,name,raw):
        original(fd,name,raw)
        if name=='proposed-container.json':case.saved.write_text('{"private":"changed"}')
    monkeypatch.setattr(review,'_write_private',write)
    with pytest.raises(RuntimeError):review.review_candidate(**options)
    assert (options['output']/'proposed-container.json').exists()
    assert not (options['output']/'review-complete.json').exists()


def test_completed_review_is_not_overwritten_or_replayed(ready):
    case,options=ready
    review.review_candidate(**options)
    before={p.name:p.read_bytes() for p in options['output'].iterdir()}
    with pytest.raises(RuntimeError):review.review_candidate(**options)
    assert before=={p.name:p.read_bytes() for p in options['output'].iterdir()}
    case.unchanged()


def test_published_digest_is_bound_to_both_private_proposals(ready):
    case,options=ready
    reference='ghcr.io/nvmagma/media_collection_auditor@sha256:'+'d'*64
    options['image']['RepoDigests']=[reference]
    report=review.review_candidate(**options,reference=reference)
    assert report['image_reference_status']=='verified_cached_digest'
    assert report['reference']==reference and not report['deployment_authorized']
    assert json.loads((options['output']/'proposed-container.json').read_bytes())['Image']==reference
    assert ET.fromstring((options['output']/'proposed-template.xml').read_bytes()).findtext('Repository')==reference
    case.unchanged()


@pytest.mark.parametrize('reference',[
    'ghcr.io/nvmagma/media_collection_auditor:latest',
    'ghcr.io/nvmagma/media_collection_auditor@sha256:'+'e'*64])
def test_unverified_reference_never_creates_a_proposal(ready,reference):
    case,options=ready
    with pytest.raises(ValueError):review.review_candidate(**options,reference=reference)
    assert not list(options['output'].iterdir())
